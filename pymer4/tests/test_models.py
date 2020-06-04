from __future__ import division
from multiprocessing import get_context
from pymer4.models import Lmer, Lm, Lm2
from pymer4.utils import get_resource_path
import pandas as pd
import numpy as np
from scipy.special import logit
from scipy.stats import ttest_ind
import os
import pytest
import re

np.random.seed(10)

os.environ[
    "KMP_DUPLICATE_LIB_OK"
] = (
    "True"
)  # Recent versions of rpy2 sometimes cause the python kernel to die when running R code; this handles that


def test_gaussian_lm2():

    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lm2("DV ~ IV3 + IV2", group="Group", data=df)
    model.fit(summarize=False)
    assert model.coefs.shape == (3, 8)
    estimates = np.array([16.11554138, -1.38425772, 0.59547697])
    assert np.allclose(model.coefs["Estimate"], estimates, atol=0.001)
    assert model.fixef.shape == (47, 3)

    # Test bootstrapping and permutation tests
    model.fit(permute=500, conf_int="boot", n_boot=500, summarize=False)
    assert model.ci_type == "boot (500)"
    assert model.sig_type == "permutation (500)"


def test_gaussian_lm():

    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lm("DV ~ IV1 + IV3", data=df)
    model.fit(summarize=False)

    assert model.coefs.shape == (3, 8)
    estimates = np.array([42.24840439, 0.24114414, -3.34057784])
    assert np.allclose(model.coefs["Estimate"], estimates, atol=0.001)

    # Test robust SE against statsmodels
    standard_se = np.array([6.83783939, 0.30393886, 3.70656475])
    assert np.allclose(model.coefs["SE"], standard_se, atol=0.001)

    hc0_se = np.array([7.16661817, 0.31713064, 3.81918182])
    model.fit(robust="hc0", summarize=False)
    assert np.allclose(model.coefs["SE"], hc0_se, atol=0.001)

    hc1_se = np.array([7.1857547, 0.31797745, 3.82937992])
    # hc1 is the default
    model.fit(robust=True, summarize=False)
    assert np.allclose(model.coefs["SE"], hc1_se, atol=0.001)

    hc2_se = np.array([7.185755, 0.317977, 3.829380])
    model.fit(robust="hc1", summarize=False)
    assert np.allclose(model.coefs["SE"], hc2_se, atol=0.001)

    hc3_se = np.array([7.22466699, 0.31971942, 3.84863701])
    model.fit(robust="hc3", summarize=False)
    assert np.allclose(model.coefs["SE"], hc3_se, atol=0.001)

    hac_lag1_se = np.array([8.20858448, 0.39184764, 3.60205873])
    model.fit(robust="hac", summarize=False)
    assert np.allclose(model.coefs["SE"], hac_lag1_se, atol=0.001)

    # Test bootstrapping
    model.fit(summarize=False, conf_int="boot")
    assert model.ci_type == "boot (500)"

    # Test permutation
    model.fit(summarize=False, permute=500)
    assert model.sig_type == "permutation (500)"

    # Test WLS
    df_two_groups = df.query("IV3 in [0.5, 1.0]").reset_index(drop=True)
    x = df_two_groups.query("IV3 == 0.5").DV.values
    y = df_two_groups.query("IV3 == 1.0").DV.values

    # Fit new a model using a categorical predictor with unequal variances (WLS)
    model = Lm("DV ~ IV3", data=df_two_groups)
    model.fit(summarize=False, weights="IV3")
    assert model.estimator == "WLS"
    
    # Make sure welch's t-test lines up with scipy
    wls = np.abs(model.coefs.loc["IV3", ["T-stat", "P-val"]].values)
    scit = np.abs(ttest_ind(x, y, equal_var=False))
    assert all([np.allclose(a, b) for a, b in zip(wls, scit)])


def test_gaussian_lmm():

    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lmer("DV ~ IV3 + IV2 + (IV2|Group) + (1|IV3)", data=df)
    opt_opts = "optimizer='Nelder_Mead', optCtrl = list(FtolAbs=1e-8, XtolRel=1e-8)"
    model.fit(summarize=False, control=opt_opts)

    assert model.coefs.shape == (3, 8)
    estimates = np.array([12.04334602, -1.52947016, 0.67768509])
    assert np.allclose(model.coefs["Estimate"], estimates, atol=0.001)

    assert isinstance(model.fixef, list)
    assert model.fixef[0].shape == (47, 3)
    assert model.fixef[1].shape == (3, 3)

    assert isinstance(model.ranef, list)
    assert model.ranef[0].shape == (47, 2)
    assert model.ranef[1].shape == (3, 1)

    assert model.ranef_corr.shape == (1, 3)
    assert model.ranef_var.shape == (4, 3)

    assert np.allclose(model.coefs.loc[:, "Estimate"], model.fixef[0].mean(), atol=0.01)

    # Test prediction
    assert np.allclose(model.predict(model.data, use_rfx=True), model.data.fits)

    # Smoketest for simulate
    model.simulate(2)
    model.simulate(2, use_rfx=True)

    # Smoketest for old_optimizer
    model.fit(summarize=False, old_optimizer=True)


def test_post_hoc():
    np.random.seed(1)
    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lmer("DV ~ IV1*IV3*DV_l + (IV1|Group)", data=df, family="gaussian")
    model.fit(
        factors={"IV3": ["0.5", "1.0", "1.5"], "DV_l": ["0", "1"]}, summarize=False
    )

    marginal, contrasts = model.post_hoc(marginal_vars="IV3", p_adjust="dunnet")
    assert marginal.shape[0] == 3
    assert contrasts.shape[0] == 3

    marginal, contrasts = model.post_hoc(marginal_vars=["IV3", "DV_l"])
    assert marginal.shape[0] == 6
    assert contrasts.shape[0] == 15


def test_logistic_lmm():

    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lmer("DV_l ~ IV1+ (IV1|Group)", data=df, family="binomial")
    model.fit(summarize=False)

    assert model.coefs.shape == (2, 13)
    estimates = np.array([-0.16098421, 0.00296261])
    assert np.allclose(model.coefs["Estimate"], estimates, atol=0.001)

    assert isinstance(model.fixef, pd.core.frame.DataFrame)
    assert model.fixef.shape == (47, 2)

    assert isinstance(model.ranef, pd.core.frame.DataFrame)
    assert model.ranef.shape == (47, 2)

    assert np.allclose(model.coefs.loc[:, "Estimate"], model.fixef.mean(), atol=0.01)

    # Test prediction
    assert np.allclose(model.predict(model.data, use_rfx=True), model.data.fits)
    assert np.allclose(
        model.predict(model.data, use_rfx=True, pred_type="link"),
        logit(model.data.fits),
    )

    # Test RFX only
    model = Lmer("DV_l ~ 0 + (IV1|Group)", data=df, family="binomial")
    model.fit(summarize=False)
    assert model.fixef.shape == (47, 2)

    model = Lmer("DV_l ~ 0 + (IV1|Group) + (1|IV3)", data=df, family="binomial")
    model.fit(summarize=False)
    assert isinstance(model.fixef, list)
    assert model.fixef[0].shape == (47, 2)
    assert model.fixef[1].shape == (3, 2)


def test_anova():

    np.random.seed(1)
    data = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    data["DV_l2"] = np.random.randint(0, 4, data.shape[0])
    model = Lmer("DV ~ IV3*DV_l2 + (IV3|Group)", data=data)
    model.fit(summarize=False)
    out = model.anova()
    assert out.shape == (3, 7)


def test_poisson_lmm():
    np.random.seed(1)
    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    df["DV_int"] = np.random.randint(1, 10, df.shape[0])
    m = Lmer("DV_int ~ IV3 + (1|Group)", data=df, family="poisson")
    m.fit(summarize=False)
    assert m.family == "poisson"
    assert m.coefs.shape == (2, 7)
    assert "Z-stat" in m.coefs.columns

    # Test RFX only
    model = Lmer("DV_int ~ 0 + (IV1|Group)", data=df, family="poisson")
    model.fit(summarize=False)
    assert model.fixef.shape == (47, 2)

    model = Lmer("DV_int ~ 0 + (IV1|Group) + (1|IV3)", data=df, family="poisson")
    model.fit(summarize=False)
    assert isinstance(model.fixef, list)
    assert model.fixef[0].shape == (47, 2)
    assert model.fixef[1].shape == (3, 2)


def test_gamma_lmm():

    np.random.seed(1)
    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    df["DV_g"] = np.random.uniform(1, 2, size=df.shape[0])
    m = Lmer("DV_g ~ IV3 + (1|Group)", data=df, family="gamma")
    m.fit(summarize=False)
    assert m.family == "gamma"
    assert m.coefs.shape == (2, 7)

    # Test RFX only; these work but the optimizer in R typically crashes if the model is especially bad fit so commenting out until a better dataset is acquired
    
    # model = Lmer("DV_g ~ 0 + (IV1|Group)", data=df, family="gamma")
    # model.fit(summarize=False)
    # assert model.fixef.shape == (47, 2)

    # model = Lmer("DV_g ~ 0 + (IV1|Group) + (1|IV3)", data=df, family="gamma")
    # model.fit(summarize=False)
    # assert isinstance(model.fixef, list)
    # assert model.fixef[0].shape == (47, 2)
    # assert model.fixef[1].shape == (3, 2)


def test_inverse_gaussian_lmm():

    np.random.seed(1)
    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    df["DV_g"] = np.random.uniform(1, 2, size=df.shape[0])
    m = Lmer("DV_g ~ IV3 + (1|Group)", data=df, family="inverse_gaussian")
    m.fit(summarize=False)
    assert m.family == "inverse_gaussian"
    assert m.coefs.shape == (2, 7)

    # Test RFX only; these work but the optimizer in R typically crashes if the model is especially bad fit so commenting out until a better dataset is acquired

    # model = Lmer("DV_g ~ 0 + (IV1|Group)", data=df, family="inverse_gaussian")
    # model.fit(summarize=False)
    # assert model.fixef.shape == (47, 2)

    # model = Lmer("DV_g ~ 0 + (IV1|Group) + (1|IV3)", data=df, family="inverse_gaussian")
    # model.fit(summarize=False)
    # assert isinstance(model.fixef, list)
    # assert model.fixef[0].shape == (47, 2)
    # assert model.fixef[1].shape == (3, 2)


def test_lmer_opt_passing():
    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lmer("DV ~ IV2 + (IV2|Group)", data=df)
    opt_opts = "optCtrl = list(ftol_abs=1e-8, xtol_abs=1e-8)"
    model.fit(summarize=False, control=opt_opts)
    estimates = np.array([10.301072, 0.682124])
    assert np.allclose(model.coefs["Estimate"], estimates, atol=0.001)
    assert len(model.warnings) == 0

    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    model = Lmer("DV ~ IV2 + (IV2|Group)", data=df)
    opt_opts = "optCtrl = list(ftol_abs=1e-4, xtol_abs=1e-4)"
    model.fit(summarize=False, control=opt_opts)
    assert len(model.warnings) >= 1


def test_glmer_opt_passing():
    np.random.seed(1)
    df = pd.read_csv(os.path.join(get_resource_path(), "sample_data.csv"))
    df["DV_int"] = np.random.randint(1, 10, df.shape[0])
    m = Lmer("DV_int ~ IV3 + (1|Group)", data=df, family="poisson")
    m.fit(
        summarize=False, control="optCtrl = list(FtolAbs=1e-1, FtolRel=1e-1, maxfun=10)"
    )
    assert len(m.warnings) >= 1


# all or prune to suit
# tests_ = [
#     test_gaussian_lm2,
#     test_gaussian_lm,
#     test_gaussian_lmm,
#     test_post_hoc,
#     test_logistic_lmm,
#     test_anova,
#     test_poisson_lmm,
#     test_gamma_lmm,
#     test_inverse_gaussian_lmm,
#     test_lmer_opt_passing,
#     test_glmer_opt_passing,
# ]

# @pytest.mark.parametrize("model", tests_)
tests_ = [eval(v) for v in locals() if re.match(r"^test_",  str(v))]
def test_Pool():
    # squeeze model functions through Pool pickling
    with get_context("spawn").Pool(processes=2) as pool:
        for test in tests_:
            print("Pool", test.__name__)
            pool.apply(test, [])
    pool.join()
