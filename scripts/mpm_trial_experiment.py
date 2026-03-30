"""MPM Revisit Trial Experiment v3 - Fast version"""
import numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
np.random.seed(42)

import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
fm.fontManager.addfont('/usr/share/fonts/truetype/chinese/SimHei.ttf')
plt.rcParams['font.sans-serif'] = ['SimHei']; plt.rcParams['axes.unicode_minus'] = False

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score, confusion_matrix
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from imblearn.over_sampling import RandomOverSampler, SMOTE, BorderlineSMOTE
from imblearn.ensemble import EasyEnsembleClassifier, BalancedRandomForestClassifier, RUSBoostClassifier
from sklearn.tree import DecisionTreeClassifier
from scipy import stats

# Data
N, D = 2000, 128
cn = ['Epithelioid', 'Biphasic', 'Sarcomatoid']
ratios = [0.73, 0.20, 0.05]
npc = [int(N*r) for r in ratios]; npc[2] = N - sum(npc[:2])
print(f"Data: {N} samples, {D} features, dist={dict(zip(cn,npc))}")

base = np.random.randn(D)
cents = np.array([base*0.3, 0.6*base*0.3+0.4*(base*0.3+np.random.randn(D)*0.6)+np.random.randn(D)*0.2, base*0.3+np.random.randn(D)*0.6])
X, y = [], []
for i,n in enumerate(npc):
    X.append(cents[i]+np.random.randn(n,D)*1.5); y.append(np.full(n,i))
X, y = np.vstack(X), np.hstack(y)
idx = np.random.permutation(N); X, y = X[idx], y[idx]

skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)

def run(name, func):
    yt,yp,ypro,fba = [],[],[],[]
    for tr,te in skf.split(X,y):
        sc = StandardScaler(); Xt=sc.fit_transform(X[tr]); Xv=sc.transform(X[te])
        m,Xp = func(Xt,y[tr],Xv)
        p = m.predict(Xp)
        pr = m.predict_proba(Xp) if hasattr(m,'predict_proba') else np.eye(3)[p]
        yt.extend(y[te]); yp.extend(p); ypro.extend(pr); fba.append(balanced_accuracy_score(y[te],p))
    yt,yp,ypro = np.array(yt),np.array(yp),np.array(ypro)
    r = {'Overall Accuracy':accuracy_score(yt,yp),'Balanced Accuracy':balanced_accuracy_score(yt,yp),
         'Macro-F1':f1_score(yt,yp,average='macro'),'Weighted-F1':f1_score(yt,yp,average='weighted'),
         'Macro-AUC':roc_auc_score(yt,ypro,multi_class='ovr',average='macro'),
         'CM':confusion_matrix(yt,yp),'yt':yt,'yp':yp,'ypro':ypro,'fba':fba}
    for i,c in enumerate(cn):
        bt=(yt==i).astype(int); bp=(yp==i).astype(int)
        r[f'{c} Precision']=precision_score(bt,bp,zero_division=0)
        r[f'{c} Recall']=recall_score(bt,bp,zero_division=0)
        r[f'{c} F1']=f1_score(bt,bp,zero_division=0)
    return r

def f_base(Xt,yt,Xv): m=LogisticRegression(max_iter=300,random_state=42); m.fit(Xt,yt); return m,Xv
def f_2011(Xt,yt,Xv): Xr,yr=RandomOverSampler(random_state=42).fit_resample(Xt,yt); m=RandomForestClassifier(n_estimators=60,max_depth=8,random_state=42,n_jobs=-1); m.fit(Xr,yr); return m,Xv
def f_smote(Xt,yt,Xv): Xr,yr=SMOTE(random_state=42,k_neighbors=5).fit_resample(Xt,yt); m=RandomForestClassifier(n_estimators=60,max_depth=8,random_state=42,n_jobs=-1); m.fit(Xr,yr); return m,Xv
def f_cblr(Xt,yt,Xv): m=LogisticRegression(max_iter=300,random_state=42,class_weight='balanced'); m.fit(Xt,yt); return m,Xv
def f_ee(Xt,yt,Xv): m=EasyEnsembleClassifier(n_estimators=8,estimator=RandomForestClassifier(n_estimators=30,max_depth=6,random_state=42),random_state=42,n_jobs=-1); m.fit(Xt,yt); return m,Xv
def f_brf(Xt,yt,Xv): m=BalancedRandomForestClassifier(n_estimators=100,max_depth=8,random_state=42,n_jobs=-1); m.fit(Xt,yt); return m,Xv
def f_rus(Xt,yt,Xv): m=RUSBoostClassifier(n_estimators=80,estimator=DecisionTreeClassifier(max_depth=3),random_state=42); m.fit(Xt,yt); return m,Xv
def f_bsm(Xt,yt,Xv): Xr,yr=BorderlineSMOTE(random_state=42,k_neighbors=5).fit_resample(Xt,yt); m=RandomForestClassifier(n_estimators=60,max_depth=8,random_state=42,n_jobs=-1); m.fit(Xr,yr); return m,Xv

methods = {'Baseline (LR)':f_base,'2011 Revisit (ROS+RF)':f_2011,'SMOTE + RF':f_smote,
           'Class-Balanced LR':f_cblr,'EasyEnsemble':f_ee,'Balanced RF':f_brf,
           'RUSBoost':f_rus,'BSMOTE + RF':f_bsm}

results = {}
for n,f in methods.items():
    print(f"  {n}...", end=' ', flush=True)
    results[n] = run(n,f)
    r=results[n]; print(f"Acc={r['Overall Accuracy']:.3f} BalAcc={r['Balanced Accuracy']:.3f} MF1={r['Macro-F1']:.3f} SarF1={r['Sarcomatoid F1']:.3f}")

# Tables
oms = ['Overall Accuracy','Balanced Accuracy','Macro-F1','Weighted-F1','Macro-AUC']
ml = list(results.keys())
print("\n"+"="*85)
print("TABLE 1: Overall Metrics (3-fold CV)")
print("="*85)
h = f"{'Method':<24}"+"".join(f"{m:>14}" for m in oms); print(h); print("-"*len(h))
for n in ml: print(f"{n:<24}"+"".join(f"{results[n][k]:>14.4f}" for k in oms))

print("\n"+"="*70)
print("TABLE 2: Per-class F1")
print("="*70)
h = f"{'Method':<24}"+"".join(f"{c:>14}" for c in cn); print(h); print("-"*len(h))
for n in ml: print(f"{n:<24}"+"".join(f"{results[n][f'{c} F1']:>14.4f}" for c in cn))

print("\n"+"="*80)
print("TABLE 3: Detailed Per-class Metrics")
print("="*80)
h = f"{'Method':<20} {'Class':<14} {'Prec':>8} {'Recall':>8} {'F1':>8}"; print(h); print("-"*len(h))
for n in ml:
    for c in cn: print(f"{n:<20} {c:<14} {results[n][f'{c} Precision']:>8.4f} {results[n][f'{c} Recall']:>8.4f} {results[n][f'{c} F1']:>8.4f}")

print("\n"+"="*70)
print("TABLE 4: Significance vs Baseline (paired t-test)")
print("="*70)
bl='Baseline (LR)'
h = f"{'Method':<24} {'ΔBalAcc':>10} {'p-value':>10} {'Sig':>6}"; print(h); print("-"*len(h))
for n in ml:
    if n==bl: continue
    t,p=stats.ttest_rel(results[n]['fba'],results[bl]['fba'])
    d=np.mean(results[n]['fba'])-np.mean(results[bl]['fba'])
    s="***" if p<0.001 else "**" if p<0.01 else "*" if p<0.05 else "n.s."
    print(f"{n:<24} {d:>+10.4f} {p:>10.4f} {s:>6}")

# Figures
print("\nGenerating figures...")
x=np.arange(len(ml))

# Fig1
fig,ax=plt.subplots(1,2,figsize=(16,7))
w=0.16; cs=['#4472C4','#ED7D31','#70AD47','#FFC000','#5B9BD5']
for i,m in enumerate(oms):
    ax[0].bar(x+i*w,[results[n][m] for n in ml],w,label=m,color=cs[i],alpha=0.85)
ax[0].set_title('Overall Metrics Comparison\n(Simulated TCGA-MESO, 3-fold CV)',fontsize=13,fontweight='bold')
ax[0].set_xticks(x+w*2); ax[0].set_xticklabels(ml,rotation=45,ha='right',fontsize=9)
ax[0].legend(fontsize=9,loc='lower right'); ax[0].set_ylim(0.4,1.02); ax[0].grid(axis='y',alpha=0.3)

w2=0.25; cc=['#4472C4','#ED7D31','#C00000']
for i,c in enumerate(cn):
    ax[1].bar(x+i*w2,[results[n][f'{c} F1'] for n in ml],w2,label=c,color=cc[i],alpha=0.85)
ax[1].set_title('Per-class F1 Scores\n(Red = Sarcomatoid, 5% of data)',fontsize=13,fontweight='bold')
ax[1].set_xticks(x+w2); ax[1].set_xticklabels(ml,rotation=45,ha='right',fontsize=9)
ax[1].legend(fontsize=10); ax[1].set_ylim(0,1.02); ax[1].grid(axis='y',alpha=0.3)
plt.tight_layout(); plt.savefig('/home/z/my-project/download/mpm_trial_fig1_metrics.png',dpi=200,bbox_inches='tight'); plt.close()

# Fig2: Confusion matrices
km = ['Baseline (LR)','2011 Revisit (ROS+RF)','SMOTE + RF','Balanced RF','RUSBoost','BSMOTE + RF']
fig,ax=plt.subplots(2,3,figsize=(18,12)); ax=ax.flatten()
for idx,mn in enumerate(km):
    cm=results[mn]['CM']; cmn=cm.astype(float)/cm.sum(1)[:,None]
    ax[idx].imshow(cmn,cmap='Blues',vmin=0,vmax=1)
    ax[idx].set_title(mn,fontsize=11,fontweight='bold')
    for i in range(3):
        for j in range(3):
            c='white' if cmn[i,j]>0.5 else 'black'
            ax[idx].text(j,i,f'{cm[i,j]}\n({cmn[i,j]:.2f})',ha='center',va='center',fontsize=10,color=c)
    ax[idx].set_xticks([0,1,2]); ax[idx].set_yticks([0,1,2])
    ax[idx].set_xticklabels(['Epi','Bip','Sar']); ax[idx].set_yticklabels(['Epi','Bip','Sar'])
    ax[idx].set_ylabel('True'); ax[idx].set_xlabel('Predicted')
fig.suptitle('Confusion Matrices (Normalized)',fontsize=14,fontweight='bold',y=1.02)
plt.tight_layout(); plt.savefig('/home/z/my-project/download/mpm_trial_fig2_confusion.png',dpi=200,bbox_inches='tight'); plt.close()

# Fig3: t-SNE
print("  t-SNE...")
Xs=StandardScaler().fit_transform(X); Xp=PCA(30).fit_transform(Xs)
Xt=TSNE(2,perplexity=25,random_state=42,n_iter=500).fit_transform(Xp)
fig,ax=plt.subplots(1,2,figsize=(16,7))
for i,(c,co) in enumerate(zip(cn,['#4472C4','#ED7D31','#C00000'])):
    m=y==i; ax[0].scatter(Xt[m,0],Xt[m,1],c=co,label=f'{c} (n={m.sum()})',alpha=0.6,s=8,edgecolors='none')
ax[0].set_title('True Labels (t-SNE)',fontsize=13,fontweight='bold'); ax[0].legend(fontsize=10)
best=max(results.keys(),key=lambda k:results[k]['Balanced Accuracy'])
yp=results[best]['yp']; ok=yp==y
for i,(c,co) in enumerate(zip(cn,['#4472C4','#ED7D31','#C00000'])):
    m=y==i
    ax[1].scatter(Xt[m&ok,0],Xt[m&ok,1],c=co,label=f'{c} ✓',alpha=0.6,s=8,edgecolors='none')
    ax[1].scatter(Xt[m&~ok,0],Xt[m&~ok,1],c=co,alpha=0.4,s=25,marker='x',linewidths=1.5)
ax[1].set_title(f'{best}\n(× = misclassified)',fontsize=13,fontweight='bold'); ax[1].legend(fontsize=10)
plt.tight_layout(); plt.savefig('/home/z/my-project/download/mpm_trial_fig3_tsne.png',dpi=200,bbox_inches='tight'); plt.close()

# Fig4: Sarcomatoid focus
fig,ax=plt.subplots(1,2,figsize=(14,6))
sf1=[results[n]['Sarcomatoid F1'] for n in ml]
sr=[results[n]['Sarcomatoid Recall'] for n in ml]
sp=[results[n]['Sarcomatoid Precision'] for n in ml]
ax[0].bar(x-0.2,sp,0.2,label='Precision',color='#4472C4',alpha=0.85)
ax[0].bar(x,sr,0.2,label='Recall',color='#ED7D31',alpha=0.85)
ax[0].bar(x+0.2,sf1,0.2,label='F1',color='#70AD47',alpha=0.85)
ax[0].axhline(y=results[bl]['Sarcomatoid F1'],color='gray',ls='--',alpha=0.5,label='Baseline')
ax[0].set_xticks(x); ax[0].set_xticklabels(ml,rotation=45,ha='right',fontsize=9)
ax[0].set_title('Sarcomatoid (肉瘤样型) Performance\nMost Critical Minority Class',fontsize=13,fontweight='bold')
ax[0].legend(); ax[0].set_ylim(0,1.02); ax[0].grid(axis='y',alpha=0.3)

ba=[results[n]['Balanced Accuracy'] for n in ml]; mf=[results[n]['Macro-F1'] for n in ml]
for i,n in enumerate(ml):
    c='#C00000' if '2011' in n else '#4472C4' if 'Baseline' in n else '#70AD47'
    ax[1].scatter(ba[i],mf[i],c=c,s=100,alpha=0.8,edgecolors='black',linewidths=0.5)
    ax[1].annotate(n[:18],(ba[i],mf[i]),fontsize=8,xytext=(5,5),textcoords='offset points')
ax[1].set_xlabel('Balanced Accuracy'); ax[1].set_ylabel('Macro-F1')
ax[1].set_title('Balanced Accuracy vs Macro-F1',fontsize=13,fontweight='bold'); ax[1].grid(alpha=0.3)
plt.tight_layout(); plt.savefig('/home/z/my-project/download/mpm_trial_fig4_sarcomatoid.png',dpi=200,bbox_inches='tight'); plt.close()

# CSV
rows=[]
for n,r in results.items():
    row={'Method':n}
    for k in oms: row[k]=r[k]
    for c in cn: row[f'{c}_Precision']=r[f'{c} Precision']; row[f'{c}_Recall']=r[f'{c} Recall']; row[f'{c}_F1']=r[f'{c} F1']
    rows.append(row)
pd.DataFrame(rows).to_csv('/home/z/my-project/download/mpm_trial_results.csv',index=False,float_format='%.4f')

srows=[]
for n in ml:
    if n==bl: continue
    t,p=stats.ttest_rel(results[n]['fba'],results[bl]['fba'])
    d=np.mean(results[n]['fba'])-np.mean(results[bl]['fba'])
    s="***" if p<0.001 else "**" if p<0.01 else "*" if p<0.05 else "n.s."
    srows.append({'Method':n,'Delta_BalAcc':round(d,4),'p_value':round(p,4),'Significance':s})
pd.DataFrame(srows).to_csv('/home/z/my-project/download/mpm_trial_significance.csv',index=False)

print("\n"+"="*60)
print("DONE")
print("="*60)
bb=max(ml,key=lambda k:results[k]['Balanced Accuracy'])
bf=max(ml,key=lambda k:results[k]['Macro-F1'])
bs=ml[sf1.index(max(sf1))]
print(f"Best BalAcc: {bb} ({results[bb]['Balanced Accuracy']:.4f})")
print(f"Best MacroF1: {bf} ({results[bf]['Macro-F1']:.4f})")
print(f"Best SarF1: {bs} ({max(sf1):.4f})")
print(f"Baseline SarF1: {results[bl]['Sarcomatoid F1']:.4f}")
print(f"Sarcomatoid F1 gain: {max(sf1)-results[bl]['Sarcomatoid F1']:+.4f}")
