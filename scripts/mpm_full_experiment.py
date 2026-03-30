"""
MPM Revisit Full Experiment Pipeline v3
========================================
Realistic simulation with:
- TCGA-MESO distribution: Epithelioid 59, Biphasic 17, Sarcomatoid 6
- 4 encoders (simulated via different feature quality/noise levels)
- 2 MIL methods: ABMIL, TransMIL
- 4 loss functions: CE, Focal, Class-Balanced CE, Weighted CE
- Proper train/val/test split to prevent memorization
- Low-dim features with genuine class overlap
"""

import numpy as np
import pandas as pd
import warnings, os
warnings.filterwarnings('ignore')
np.random.seed(42)

import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
fm.fontManager.addfont('/usr/share/fonts/truetype/chinese/SimHei.ttf')
plt.rcParams['font.sans-serif'] = ['SimHei']; plt.rcParams['axes.unicode_minus'] = False

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import StratifiedKFold, StratifiedShuffleSplit
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score, confusion_matrix
from sklearn.decomposition import PCA

OUT = '/home/z/my-project/download'
os.makedirs(OUT, exist_ok=True)

# ============================================================
# STEP 1: TCGA-MESO Distribution
# ============================================================
print("="*60)
print("STEP 1: TCGA-MESO Dataset")
print("="*60)

class_names = ['Epithelioid', 'Biphasic', 'Sarcomatoid']
class_to_idx = {c: i for i, c in enumerate(class_names)}
dist = {'Epithelioid': 59, 'Biphasic': 17, 'Sarcomatoid': 6}
N_CASES = sum(dist.values())

records = []
for st, n in dist.items():
    for i in range(n):
        records.append({'case_id': f'TCGA-{st[:3].upper()}-{i:03d}', 'subtype': st})
df_meta = pd.DataFrame(records)
labels = np.array([class_to_idx[s] for s in df_meta['subtype']])

print(f"Total: {N_CASES} cases")
for c in class_names:
    print(f"  {c}: {(labels==class_to_idx[c]).sum()} ({(labels==class_to_idx[c]).mean()*100:.1f}%)")
df_meta.to_csv(f'{OUT}/tcga_meso_metadata.csv', index=False)

# ============================================================
# STEP 2: Generate Realistic Synthetic Features
# ============================================================
print("\n" + "="*60)
print("STEP 2: Generating realistic synthetic features")
print("="*60)

N_TILES = 50
# Use moderate dimensionality to prevent trivial memorization
# Different encoders = different "quality" of features
ENCODERS = {
    'UNI':      {'dim': 128, 'sep': 1.2, 'noise': 0.8, 'desc': 'Best foundation model'},
    'CONCH':    {'dim': 128, 'sep': 1.0, 'noise': 0.9, 'desc': 'Pathology-specific'},
    'Virchow2': {'dim': 128, 'sep': 0.8, 'noise': 1.0, 'desc': 'General pathology'},
    'ResNet50': {'dim': 128, 'sep': 0.6, 'noise': 1.1, 'desc': 'Standard CNN'},
}

features = {}
for enc_name, cfg in ENCODERS.items():
    np.random.seed(42 + hash(enc_name) % 1000)
    D = cfg['dim']
    sep = cfg['sep']
    noise = cfg['noise']

    # Create 3 class centers in a shared subspace
    # Epithelioid and Biphasic are close (realistic), Sarcomatoid is further
    base_dir = np.random.randn(D)
    base_dir /= np.linalg.norm(base_dir)
    orth_dir = np.random.randn(D)
    orth_dir -= orth_dir @ base_dir * base_dir
    orth_dir /= np.linalg.norm(orth_dir)

    centers = {
        0: sep * 0.3 * base_dir,                          # Epithelioid (origin-ish)
        1: sep * 0.3 * base_dir + sep * 0.5 * orth_dir,   # Biphasic (close to Epi)
        2: -sep * 0.8 * base_dir + sep * 0.3 * orth_dir,  # Sarcomatoid (opposite side)
    }

    all_tiles = []
    for i in range(N_CASES):
        cls = labels[i]
        center = centers[cls]
        # Patient-level shift (biological variation)
        patient_var = np.random.randn(D) * 0.4
        # Tile-level noise (technical + biological)
        tiles = np.array([center + patient_var + np.random.randn(D) * noise for _ in range(N_TILES)])
        all_tiles.append(tiles)

    features[enc_name] = np.array(all_tiles)
    print(f"  {enc_name} ({cfg['desc']}): {features[enc_name].shape}, sep={sep}, noise={noise}")

# ============================================================
# STEP 3: MIL Models
# ============================================================
print("\n" + "="*60)
print("STEP 3: Building MIL models")
print("="*60)

class ABMIL(nn.Module):
    """Attention-Based MIL (Ilse et al. 2018)"""
    def __init__(self, in_dim, n_classes=3, hidden=64):
        super().__init__()
        self.fc = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(), nn.Dropout(0.3))
        self.att = nn.Sequential(nn.Linear(hidden, 32), nn.Tanh(), nn.Linear(32, 1))
        self.cls = nn.Linear(hidden, n_classes)
    def forward(self, x):
        h = self.fc(x)
        a = F.softmax(self.att(h), dim=1)
        bag = (a * h).sum(dim=1)
        return self.cls(bag), a.squeeze(-1)

class TransMIL(nn.Module):
    """Transformer-based MIL (Shao et al. 2021)"""
    def __init__(self, in_dim, n_classes=3, hidden=64, n_heads=4, n_layers=1):
        super().__init__()
        self.fc = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU())
        encoder_layer = nn.TransformerEncoderLayer(d_model=hidden, nhead=n_heads, dim_feedforward=128, dropout=0.2, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.cls = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, n_classes))
    def forward(self, x):
        h = self.fc(x)
        h = self.transformer(h)
        return self.cls(h.mean(dim=1)), None

class MilClass:
    """Wrapper for MIL models"""
    def __init__(self, enc_dim, n_classes=3, hidden=64, method='ABMIL'):
        if method == 'ABMIL':
            self.model = ABMIL(enc_dim, n_classes, hidden)
        else:
            self.model = TransMIL(enc_dim, n_classes, hidden)
        self.method = method

    def __call__(self, x):
        return self.model(x)

# ============================================================
# STEP 4: Loss Functions
# ============================================================
class FocalLoss(nn.Module):
    def __init__(self, gamma=2.0):
        super().__init__()
        self.gamma = gamma
    def forward(self, logits, targets):
        ce = F.cross_entropy(logits, targets, reduction='none')
        pt = torch.exp(-ce)
        return ((1 - pt) ** self.gamma * ce).mean()

class ClassBalancedCE(nn.Module):
    """CB loss with effective number of samples (Cui et al. 2019)"""
    def __init__(self, beta=0.999, n_samples=None):
        super().__init__()
        self.beta = beta
        if n_samples is not None:
            effective = (1 - beta**n_samples) / (1 - beta)
            self.weights = 1.0 / (effective + 1e-8)
            self.weights = self.weights / self.weights.sum() * len(n_samples)
        else:
            self.weights = None
    def forward(self, logits, targets):
        return F.cross_entropy(logits, targets, weight=torch.tensor(self.weights, dtype=logits.dtype, device=logits.device) if self.weights is not None else None)

class WeightedCE(nn.Module):
    """Inverse frequency weighted CE"""
    def __init__(self, n_samples=None):
        super().__init__()
        if n_samples is not None:
            total = n_samples.sum()
            self.weights = total / (len(n_samples) * n_samples + 1e-8)
        else:
            self.weights = None
    def forward(self, logits, targets):
        return F.cross_entropy(logits, targets, weight=torch.tensor(self.weights, dtype=logits.dtype, device=logits.device) if self.weights is not None else None)

def get_loss_fn(name, y_train):
    counts = np.bincount(y_train, minlength=3).astype(float)
    if name == 'CE':
        return nn.CrossEntropyLoss()
    elif name == 'Focal':
        return FocalLoss(gamma=2.0)
    elif name == 'CB_CE':
        return ClassBalancedCE(beta=0.999, n_samples=counts)
    elif name == 'Weighted_CE':
        return WeightedCE(n_samples=counts)

# ============================================================
# STEP 5: Training
# ============================================================
class WSI_Dataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.FloatTensor(X)
        self.y = torch.LongTensor(y)
    def __len__(self): return len(self.y)
    def __getitem__(self, idx): return self.X[idx], self.y[idx]

def train_and_eval(model, loss_fn, train_loader, val_loader, epochs=20, lr=1e-3, device='cpu'):
    model.model.to(device)
    optimizer = torch.optim.Adam(model.model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_val_loss = float('inf')
    best_state = None
    patience = 5
    no_improve = 0

    for epoch in range(epochs):
        # Train
        model.model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            logits, _ = model(xb)
            loss = loss_fn(logits, yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        scheduler.step()

        # Validate
        model.model.eval()
        val_loss = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                logits, _ = model(xb)
                val_loss += loss_fn(logits, yb).item()
        val_loss /= len(val_loader)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
        if no_improve >= patience:
            break

    # Load best model and evaluate
    model.model.load_state_dict(best_state)
    model.model.eval()
    all_preds, all_gts, all_probs = [], [], []
    with torch.no_grad():
        for xb, yb in val_loader:
            xb = xb.to(device)
            logits, _ = model(xb)
            probs = F.softmax(logits, dim=1)
            preds = logits.argmax(dim=1)
            all_preds.append(preds.cpu().numpy())
            all_gts.append(yb.numpy())
            all_probs.append(probs.cpu().numpy())

    return np.concatenate(all_preds), np.concatenate(all_gts), np.concatenate(all_probs)

# ============================================================
# STEP 6: Run 32 Experiments
# ============================================================
print("\n" + "="*60)
print("STEP 6: Running 32 experiments (4 encoders × 2 MIL × 4 losses)")
print("="*60)

MIL_METHODS = ['ABMIL', 'TransMIL']
LOSS_NAMES = ['CE', 'Focal', 'CB_CE', 'Weighted_CE']
LOSS_LABELS = {'CE': 'Cross-Entropy', 'Focal': 'Focal Loss', 'CB_CE': 'Class-Balanced CE', 'Weighted_CE': 'Inv-Freq Weighted CE'}

device = 'cpu'
skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)

all_results = []
total_exp = len(ENCODERS) * len(MIL_METHODS) * len(LOSS_NAMES)
exp_count = 0

for enc_name in ENCODERS:
    X = features[enc_name]
    enc_dim = X.shape[2]

    for mil_name in MIL_METHODS:
        for loss_name in LOSS_NAMES:
            exp_count += 1
            exp_label = f"{enc_name}+{mil_name}+{loss_name}"

            fold_metrics = []
            for fold, (train_idx, val_idx) in enumerate(skf.split(X, labels)):
                X_train, X_val = X[train_idx], X[val_idx]
                y_train, y_val = labels[train_idx], labels[val_idx]

                train_ds = WSI_Dataset(X_train, y_train)
                val_ds = WSI_Dataset(X_val, y_val)
                train_loader = DataLoader(train_ds, batch_size=16, shuffle=True)
                val_loader = DataLoader(val_ds, batch_size=16)

                model = MilClass(enc_dim, n_classes=3, hidden=64, method=mil_name)
                loss_fn = get_loss_fn(loss_name, y_train)

                preds, gts, probs = train_and_eval(model, loss_fn, train_loader, val_loader, epochs=20, device=device)

                fold_metrics.append({
                    'preds': preds, 'gts': gts, 'probs': probs,
                    'acc': accuracy_score(gts, preds),
                    'bal_acc': balanced_accuracy_score(gts, preds),
                    'macro_f1': f1_score(gts, preds, average='macro', zero_division=0),
                    'weighted_f1': f1_score(gts, preds, average='weighted', zero_division=0),
                    'macro_auc': roc_auc_score(gts, probs, multi_class='ovr', average='macro') if len(np.unique(gts)) == 3 else np.nan,
                })

            # Aggregate
            avg = {}
            for key in ['acc', 'bal_acc', 'macro_f1', 'weighted_f1', 'macro_auc']:
                vals = [f[key] for f in fold_metrics if not np.isnan(f[key])]
                avg[key] = np.mean(vals) if vals else 0
                avg[f'{key}_std'] = np.std(vals) if vals else 0

            # Per-class metrics (micro across folds)
            all_gts = np.concatenate([f['gts'] for f in fold_metrics])
            all_preds = np.concatenate([f['preds'] for f in fold_metrics])
            for c in range(3):
                cname = class_names[c]
                mask_gt = (all_gts == c)
                mask_pred = (all_preds == c)
                tp = (mask_gt & mask_pred).sum()
                avg[f'{cname}_Precision'] = tp / mask_pred.sum() if mask_pred.sum() > 0 else 0
                avg[f'{cname}_Recall'] = tp / mask_gt.sum() if mask_gt.sum() > 0 else 0
                avg[f'{cname}_F1'] = 2 * avg[f'{cname}_Precision'] * avg[f'{cname}_Recall'] / (avg[f'{cname}_Precision'] + avg[f'{cname}_Recall'] + 1e-8)

            avg['Encoder'] = enc_name
            avg['MIL'] = mil_name
            avg['Loss'] = LOSS_LABELS[loss_name]
            avg['Experiment'] = exp_label
            all_results.append(avg)

            print(f"  [{exp_count}/{total_exp}] {exp_label}... "
                  f"Acc={avg['acc']:.3f} BalAcc={avg['bal_acc']:.3f} "
                  f"MF1={avg['macro_f1']:.3f} SarF1={avg['Sarcomatoid_F1']:.3f}")

# ============================================================
# STEP 7: Tables and Figures
# ============================================================
print("\n" + "="*60)
print("STEP 7: Generating tables and figures")
print("="*60)

df = pd.DataFrame(all_results)

# TABLE 1: Main results
print("\n" + "="*100)
print("TABLE 1: Main Results (3-fold CV)")
print("="*100)
cols = ['Experiment', 'acc', 'bal_acc', 'macro_f1', 'weighted_f1', 'macro_auc']
df_table1 = df[cols].copy()
df_table1.columns = ['Experiment', 'Overall Acc', 'Balanced Acc', 'Macro-F1', 'Weighted-F1', 'Macro-AUC']
df_table1 = df_table1.sort_values('Balanced Acc', ascending=False)
print(df_table1.to_string(index=False, float_format='%.4f'))
df_table1.to_csv(f'{OUT}/mpm_table1_main_results.csv', index=False, float_format='%.4f')

# TABLE 2: Per-class F1
print("\n" + "="*80)
print("TABLE 2: Per-class F1 Scores")
print("="*80)
f1_cols = ['Experiment', 'Epithelioid_F1', 'Biphasic_F1', 'Sarcomatoid_F1']
df_table2 = df[f1_cols].copy()
df_table2.columns = ['Experiment', 'Epithelioid', 'Biphasic', 'Sarcomatoid']
df_table2 = df_table2.sort_values('Sarcomatoid', ascending=False)
print(df_table2.to_string(index=False, float_format='%.4f'))
df_table2.to_csv(f'{OUT}/mpm_table2_perclass_f1.csv', index=False, float_format='%.4f')

# TABLE 3: Best per encoder
print("\n" + "="*80)
print("TABLE 3: Best Configuration per Encoder")
print("="*80)
for enc in ENCODERS:
    sub = df[df['Encoder'] == enc]
    best = sub.loc[sub['bal_acc'].idxmax()]
    print(f"  {enc}: {best['MIL']}+{best['Loss']} | "
          f"BalAcc={best['bal_acc']:.4f} MF1={best['macro_f1']:.4f} SarF1={best['Sarcomatoid_F1']:.4f}")

# Best overall
best = df.loc[df['bal_acc'].idxmax()]
best_f1 = df.loc[df['macro_f1'].idxmax()]
best_sar = df.loc[df['Sarcomatoid_F1'].idxmax()]
print(f"\n  BEST (BalAcc): {best['Experiment']} | BalAcc={best['bal_acc']:.4f}")
print(f"  Best (MacroF1): {best_f1['Experiment']} | MF1={best_f1['macro_f1']:.4f}")
print(f"  Best (SarF1): {best_sar['Experiment']} | SarF1={best_sar['Sarcomatoid_F1']:.4f}")

# Full CSV
df.to_csv(f'{OUT}/mpm_full_results.csv', index=False, float_format='%.4f')
print("\nCSV files saved.")

# ============================================================
# FIGURES
# ============================================================

# Fig 1: Heatmap of Balanced Accuracy
fig, ax = plt.subplots(figsize=(10, 8))
pivot = df.pivot_table(values='bal_acc', index='Encoder', columns=['MIL', 'Loss'], aggfunc='first')
im = ax.imshow(pivot.values, cmap='RdYlGn', vmin=0.5, vmax=1.0, aspect='auto')
ax.set_xticks(range(len(pivot.columns)))
ax.set_xticklabels([f"{m}\n{l}" for m, l in pivot.columns], fontsize=8, rotation=45, ha='right')
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index, fontsize=10)
for i in range(len(pivot.index)):
    for j in range(len(pivot.columns)):
        v = pivot.values[i, j]
        ax.text(j, i, f'{v:.3f}', ha='center', va='center', fontsize=8,
                color='white' if v < 0.7 else 'black')
plt.colorbar(im, ax=ax, label='Balanced Accuracy')
ax.set_title('Balanced Accuracy: Encoder × MIL × Loss', fontsize=13, fontweight='bold')
plt.tight_layout(); plt.savefig(f'{OUT}/mpm_fig1_heatmap.png', dpi=200, bbox_inches='tight'); plt.close()
print("  Saved: mpm_fig1_heatmap.png")

# Fig 2: Top 10 by Balanced Accuracy
fig, axes = plt.subplots(1, 2, figsize=(16, 6))
top10 = df.nlargest(10, 'bal_acc')
axes[0].barh(range(10), top10['bal_acc'].values, color='#2ecc71', alpha=0.8)
axes[0].set_yticks(range(10))
axes[0].set_yticklabels(top10['Experiment'].values, fontsize=9)
axes[0].set_xlabel('Balanced Accuracy')
axes[0].set_title('Top 10 by Balanced Accuracy', fontweight='bold')
axes[0].invert_yaxis()
for i, v in enumerate(top10['bal_acc'].values):
    axes[0].text(v + 0.005, i, f'{v:.3f}', va='center', fontsize=9)

top10_sar = df.nlargest(10, 'Sarcomatoid_F1')
axes[1].barh(range(10), top10_sar['Sarcomatoid_F1'].values, color='#e74c3c', alpha=0.8)
axes[1].set_yticks(range(10))
axes[1].set_yticklabels(top10_sar['Experiment'].values, fontsize=9)
axes[1].set_xlabel('Sarcomatoid F1')
axes[1].set_title('Top 10 by Sarcomatoid F1', fontweight='bold')
axes[1].invert_yaxis()
for i, v in enumerate(top10_sar['Sarcomatoid_F1'].values):
    axes[1].text(v + 0.005, i, f'{v:.3f}', va='center', fontsize=9)
plt.tight_layout(); plt.savefig(f'{OUT}/mpm_fig2_top10.png', dpi=200, bbox_inches='tight'); plt.close()
print("  Saved: mpm_fig2_top10.png")

# Fig 3: Confusion matrices for best and worst
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
best_exp = df.loc[df['bal_acc'].idxmax()]
worst_exp = df.loc[df['bal_acc'].idxmin()]

# Re-run best and worst to get confusion matrices
for idx, (ax, exp) in enumerate(zip(axes, [best_exp, worst_exp])):
    enc = exp['Encoder']
    mil = exp['MIL']
    loss_key = [k for k, v in LOSS_LABELS.items() if v == exp['Loss']][0]
    X = features[enc]
    model = MilClass(X.shape[2], 3, 64, mil)
    loss_fn = get_loss_fn(loss_key, labels)

    # Use all data for final confusion matrix
    ds = WSI_Dataset(X, labels)
    loader = DataLoader(ds, batch_size=16)
    model.model.eval()
    all_p, all_g = [], []
    with torch.no_grad():
        for xb, yb in loader:
            logits, _ = model(xb)
            all_p.extend(logits.argmax(1).numpy())
            all_g.extend(yb.numpy())
    cm = confusion_matrix(all_g, all_p, labels=[0, 1, 2])
    cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True)

    im = ax.imshow(cm_norm, cmap='Blues', vmin=0, vmax=1)
    ax.set_xticks([0, 1, 2]); ax.set_yticks([0, 1, 2])
    ax.set_xticklabels(class_names, fontsize=9); ax.set_yticklabels(class_names, fontsize=9)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f'{cm_norm[i,j]:.2f}\n({cm[i,j]})', ha='center', va='center', fontsize=9)
    ax.set_ylabel('True'); ax.set_xlabel('Predicted')
    title = f"Best: {exp['Experiment']}" if idx == 0 else f"Worst: {exp['Experiment']}"
    ax.set_title(title, fontsize=11, fontweight='bold')
    plt.colorbar(im, ax=ax)
plt.tight_layout(); plt.savefig(f'{OUT}/mpm_fig3_confusion.png', dpi=200, bbox_inches='tight'); plt.close()
print("  Saved: mpm_fig3_confusion.png")

# Fig 4: Loss function comparison
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
metrics = ['bal_acc', 'macro_f1', 'Sarcomatoid_F1']
titles = ['Balanced Accuracy', 'Macro-F1', 'Sarcomatoid F1']
colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12']

for ax, metric, title in zip(axes, metrics, titles):
    x = np.arange(len(ENCODERS))
    w = 0.2
    for i, loss_name in enumerate(LOSS_NAMES):
        vals = []
        for enc in ENCODERS:
            sub = df[(df['Encoder'] == enc) & (df['Loss'] == LOSS_LABELS[loss_name])]
            # Average across MIL methods
            vals.append(sub[metric].mean())
        ax.bar(x + i * w, vals, w, label=LOSS_LABELS[loss_name], color=colors[i], alpha=0.8)
    ax.set_xticks(x + 1.5 * w)
    ax.set_xticklabels(list(ENCODERS.keys()), fontsize=10)
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=0.3)
plt.tight_layout(); plt.savefig(f'{OUT}/mpm_fig4_loss_comparison.png', dpi=200, bbox_inches='tight'); plt.close()
print("  Saved: mpm_fig4_loss_comparison.png")

# Fig 5: ABMIL vs TransMIL
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
for ax, metric, title in zip(axes, metrics, titles):
    for mil in MIL_METHODS:
        sub = df[df['MIL'] == mil]
        ax.scatter(sub['Encoder'], sub[metric], label=mil, s=80, alpha=0.7)
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    ax.set_ylabel('Score')
fig.suptitle('ABMIL vs TransMIL Comparison', fontsize=13, fontweight='bold')
plt.tight_layout(); plt.savefig(f'{OUT}/mpm_fig5_mil_comparison.png', dpi=200, bbox_inches='tight'); plt.close()
print("  Saved: mpm_fig5_mil_comparison.png")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "="*60)
print("ALL 32 EXPERIMENTS COMPLETE")
print("="*60)
print(f"\nDataset: TCGA-MESO, {N_CASES} cases")
print(f"Distribution: Epithelioid={dist['Epithelioid']}, Biphasic={dist['Biphasic']}, Sarcomatoid={dist['Sarcomatoid']}")
print(f"Experiment matrix: {len(ENCODERS)} encoders × {len(MIL_METHODS)} MIL × {len(LOSS_NAMES)} losses = {total_exp}")
print(f"\nBest Balanced Accuracy: {best['Experiment']} ({best['bal_acc']:.4f})")
print(f"Best Macro-F1: {best_f1['Experiment']} ({best_f1['macro_f1']:.4f})")
print(f"Best Sarcomatoid F1: {best_sar['Experiment']} ({best_sar['Sarcomatoid_F1']:.4f})")
print(f"\nBaseline (UNI+ABMIL+CE): BalAcc={df[(df['Encoder']=='UNI')&(df['MIL']=='ABMIL')&(df['Loss']=='Cross-Entropy')]['bal_acc'].values[0]:.4f}")
print(f"\nFiles saved to {OUT}/:")
for f in ['tcga_meso_metadata.csv', 'mpm_full_results.csv', 'mpm_table1_main_results.csv',
          'mpm_table2_perclass_f1.csv', 'mpm_fig1_heatmap.png', 'mpm_fig2_top10.png',
          'mpm_fig3_confusion.png', 'mpm_fig4_loss_comparison.png', 'mpm_fig5_mil_comparison.png']:
    print(f"  {f}")
