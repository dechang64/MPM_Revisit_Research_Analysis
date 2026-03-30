# MPM Revisit Research Analysis

Research on Malignant Pleural Mesothelioma (MPM) histological subtype classification using deep learning approaches, with TCGA-MESO dataset analysis and MIL-based methods.

## Repository Structure

```
├── MPM_Revisit_Research_Analysis.docx   # Main research document
├── data/                                 # Experimental data & results
│   ├── tcga_meso_metadata.csv            # TCGA-MESO patient metadata
│   ├── mpm_full_results.csv              # Full experiment results
│   ├── mpm_table1_main_results.csv       # Main classification results
│   ├── mpm_table2_perclass_f1.csv        # Per-class F1 scores
│   ├── mpm_trial_results.csv             # Trial experiment results
│   └── mpm_trial_significance.csv        # Statistical significance tests
├── figures/                              # Generated figures
│   ├── mpm_fig1_heatmap.png              # Feature correlation heatmap
│   ├── mpm_fig2_top10.png                # Top-10 feature importance
│   ├── mpm_fig3_confusion.png            # Confusion matrix
│   ├── mpm_fig4_loss_comparison.png      # Loss curve comparison
│   ├── mpm_fig5_mil_comparison.png       # MIL method comparison
│   ├── mpm_trial_fig1_metrics.png        # Trial: performance metrics
│   ├── mpm_trial_fig2_confusion.png      # Trial: confusion matrix
│   ├── mpm_trial_fig3_tsne.png           # Trial: t-SNE visualization
│   └── mpm_trial_fig4_sarcomatoid.png    # Trial: sarcomatoid analysis
└── scripts/                              # Experiment scripts
    ├── mpm_full_experiment.py            # Full experiment pipeline
    ├── mpm_trial_experiment.py           # Trial experiment
    └── gen_poster.py                     # Poster generation script
```

## Overview

This project investigates MPM histological subtype classification (epithelioid vs. sarcomatoid vs. biphasic) using:
- Deep learning feature extraction
- Multiple Instance Learning (MIL) approaches
- TCGA-MESO whole-slide image analysis
