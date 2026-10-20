"""Escalas para modelagem de uso em métricas muito assimétricas (tempo assistido).

Papel: mostrar o efeito de min-max, z-score, escala robusta, log e Yeo-Johnson sobre a
       mesma variável, para escolher a transformação de cada uso (modelo, cluster, painel).
Entrada: série de horas por perfil-dia (ou por conta-mês).
Saída: DataFrame com a variável em cada escala + resumo de forma (assimetria, curtose, % de
       valores comprimidos perto de zero).
Dependências: numpy, pandas, scipy, scikit-learn.

Resumo da decisão (docs/TECHNIQUES.md): min-max e z-score preservam a assimetria e deixam
quase tudo espremido perto de zero por causa da cauda; robusta centra na mediana mas também
mantém a cauda; log1p e Yeo-Johnson aproximam a forma de uma normal. Para modelos lineares e
distâncias, usamos log1p (interpretável) ou Yeo-Johnson (aceita zero e negativo).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.preprocessing import MinMaxScaler, PowerTransformer, RobustScaler, StandardScaler


def all_scales(x: pd.Series) -> pd.DataFrame:
    v = x.to_numpy(dtype=float).reshape(-1, 1)
    return pd.DataFrame({
        "original": v.ravel(),
        "min_max": MinMaxScaler().fit_transform(v).ravel(),
        "z_score": StandardScaler().fit_transform(v).ravel(),
        "robusta": RobustScaler().fit_transform(v).ravel(),
        "log1p": np.log1p(np.clip(v.ravel(), 0, None)),
        "yeo_johnson": PowerTransformer(method="yeo-johnson").fit_transform(v).ravel(),
    })


def shape_summary(scaled: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in scaled.columns:
        v = scaled[c]
        span = v.max() - v.min()
        rows.append({"escala": c, "assimetria": float(stats.skew(v)), "curtose": float(stats.kurtosis(v)),
                     "pct_no_primeiro_decimo": float(100 * (v <= v.min() + 0.1 * span).mean()),
                     "mediana": float(v.median()), "p99": float(v.quantile(.99))})
    return pd.DataFrame(rows)
