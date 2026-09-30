# Understand and demonstrate Forecast Review Workbench

## 中文：先问是否在比较同一批记录

这个工具回答：在目标、单位、预测期限一致的前提下，哪些记录可以共同比较，两份预测谁在这批记录上的误差更小？给工具一个预测文件，不能证明其训练没有泄漏。

1. 点“试用示例”，阅读覆盖情况。完整范围12个月，A有9个月，B有10个月，交集只有7个月。
2. 查看各自样本：A的MAE约1.5556，B约4.3。不能由此宣布A更好，因为月份不同。
3. 明确接受共同样本，进入结果页。相同7个月上A的MAE为2，B为1，排名反转。被排除的是2024-04、05、10、11、12；结论不适用于这5个月。
4. 下载复核包，解压打开report.html；可阅读输入定义、指标、来源、排除原因。CSV/JSON用于独立复算。示例是人为构造的预测，不是训练业绩。
5. 自己使用时，先选实际与预测文件，核对日期/数值列，再明确预期完整期间及目标/单位/期限。不要按文件现有月份自动缩窄范围，否则可能掩盖所有文件共同缺失的月份。中文常见列名可建议映射；多列同时匹配时需人工选择。

可选训练任务限于月度OLS候选，预处理在各训练窗口拟合，开发期选模型，明确揭示留出期。预测比较与训练是不同任务，不要把读取任意预测文件当成验证其训练流程。

## English introduction — about three minutes at a measured pace

Forecast Review Workbench addresses a common problem in comparing prediction files: models may appear to have different accuracy simply because they cover different observations. I built a browser-local workflow that makes the expected scope, missing records and accepted common sample explicit before presenting a comparison.

The main task starts with actual values and one to five prediction files, with an optional baseline. The user selects CSV or Excel files, confirms the date and value columns, and declares the target, unit, horizon and full expected period. The tool suggests unambiguous common column names, but it does not guess the complete expected scope from the supplied data. That would hide records absent from every file.

The example makes this concrete. There are twelve expected months. Candidate A covers nine and candidate B covers ten, but only seven are shared. On their own samples, A has an MAE of about 1.56 and B about 4.30. On the same seven months, A has an MAE of two and B one. The apparent ranking reverses. These are invented predictions designed to demonstrate a coverage trap, not model-training results.

The review keeps all excluded periods visible. The user must accept a nonempty common sample before comparison metrics appear. MAE, RMSE and signed bias then use identical keys. Changing inputs or definitions invalidates the old acceptance and review notes. A downloaded evidence bundle includes a readable offline report, row diagnostics, declarations and source fingerprints, allowing someone else to recompute the results.

The repository also contains monthly regression experiments and additive financial reconciliation, but these are secondary workflows. The experiment workflow fits preprocessing within each training window and selects candidates on development data before explicitly revealing holdout performance. I reused and attributed the numerical kernel from my own public Model Risk Lab rather than claiming an independently written second engine.

The main limitation is that software can check declared definitions and supplied records, but it cannot authenticate the source or reconstruct an arbitrary prediction file's training history. A smaller common-sample error does not resolve missing coverage, prove future performance, or approve a model. External human adoption has not been verified. The project's value is making comparison assumptions and evidence inspectable rather than producing a flattering model ranking.

## Five technical follow-ups

1. **Why not compare each file's full sample?** Different periods/entities have different difficulty. Use the same valid expected keys; keep own-sample metrics diagnostic only.
2. **Does common-sample comparison remove selection bias?** No. Missingness may be systematic. Report excluded keys and limit the conclusion to the intersection.
3. **How is leakage addressed in training?** Preprocessing is fitted on training windows and selection uses development data. Information-release lags remain caller declarations; arbitrary imported forecasts cannot prove leakage-free training.
4. **Why keep a baseline?** It checks whether complexity improves error on the same sample. Percentage improvement is undefined when the baseline error is zero.
5. **What do hashes prove?** They help identify changes in selected source content and exports, not authenticity, causality, predictive skill or model approval.

## Personal understanding gate — pending

Reproduce the ranking reversal in your own words, explain why excluded months still matter, then give the English introduction and answer the five follow-ups. This personal assessment remains pending; generated materials are not proof of understanding.
