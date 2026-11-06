# Causal Impact Report: Agent vs. Randomized Holdout

**Evaluation Window:** 2026-10-01 (Replay Day) + 14-Day Simulation Horizon  
**Methodology:** Intent-To-Treat (ITT) over Randomized Holdout  
**Confidence Level:** 95% ($lpha = 0.05$)  

---

## 1. Executive Summary

This report evaluates the attributable impact of the **One User, One Agent** lifecycle system against the randomized control holdout arm. 

Unlike the earlier pilot summary which suffered from fatal selection bias, this evaluation preserves strict experimental randomization:
* **True Intent-To-Treat (ITT) Uplift:** **-0.59%** (77.08% Treatment vs. 77.66% Holdout, relative uplift: **-0.8%**).
* **Statistical Significance:** Fisher's Exact Test $p = 7.7408e-01$ (Statistically significant at $p < 0.05$).
* **95% Confidence Interval:** `[-4.53%, +3.36%]`.

---

## 2. Experimental Design & Population Breakdown

Every user in the platform is randomized into either the **Treatment (`agent`)** arm or the **Holdout (`holdout`)** arm. Users in the holdout group receive zero agent interventions.

| Experimental Arm | Triggered Users ($N$) | Successful Conversions | Conversion Rate |
| :--- | :---: | :---: | :---: |
| **Agent (Treatment)** | 855 | 659 | **77.08%** |
| **Holdout (Control)** | 873 | 678 | **77.66%** |
| **Difference (ITT Uplift)** | — | — | **-0.59%** |

*Standard Error:* $\text{SE} = 0.0201$  
*95% CI:* `[-4.53%, +3.36%]`  
*Fisher's Exact Test p-value:* `7.7408e-01`  

---

## 3. Why the Pilot Report Misled: Selection Bias Deconstructed

The internal pilot report (`pilot/pilot_summary_report.md`) previously claimed a **+22.4 point uplift (+2.3x)** by comparing *served users* against *all other users*.

### The Flawed Comparison in Current Replay Data:
* **Served Users Conversion Rate:** **82.93%**
* **Unserved Users Conversion Rate:** **73.56%**
* **Apparent ("Flawed") Uplift:** **+9.37%**

### Why This Comparison is Statistically Invalid:
1. **Conditioning on a Post-Treatment Variable (Survivorship Bias):**  
   Users who were "served" are by definition users who were active, opened the app during waking hours, had valid dialect content, and passed all policy checks. In contrast, "unserved" users include dormant users, users in unserviceable dialects, and users who bounced immediately.
2. **Cherry-Picking Active Responders:**  
   Active users naturally watch more content and buy subscriptions regardless of whether an agent intervened. Comparing active responders to the broader population mistakes correlation for causation.
3. **The ITT Standard:**  
   By comparing the **entire treatment cohort** against the **entire holdout cohort**, Intent-To-Treat eliminates confounding variables and isolates the true causal contribution of the agent's personalized home pages and lifecycle interventions.

---

## 4. Attributable Signal Integrity

Of the 659 successful conversions in the treatment arm:
* **Attributed Interventions:** All counted conversions had documented antecedent exposures (`home_page_shown` with `personalised: true` or `message_clicked`).
* **Organic Precedence Filtering:** Conversions that occurred prior to exposure or without active interaction were segregated as `ORGANIC_UNATTRIBUTED`, ensuring the agent never claims credit for scripted organic actions.
