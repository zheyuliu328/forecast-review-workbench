# Invented coverage example

These four CSV files contain newly invented actuals, two candidate forecasts and a supplied baseline. They are deliberately constructed and were not trained on data.

Select the files manually in the GUI; each uses different headers. Set the target to the declaration in request.json, select monthly scope 2024-01 through 2024-12, and copy that definition to all sources after checking it. The GUI example button fills these same settings for convenience.

Expected result: 12 expected months, 7 shared months, 5 exclusions. Candidate A covers 9/12 and appears better on its own easier sample; Candidate B covers 10/12 and has smaller error on the common seven months. Coverage gaps still limit the conclusion.

For a coverage-only CLI export, run `forecast-review --review examples/request.json --output /path/to/new-directory` from the checkout. Exit 1 means comparison is pending. To compute shared metrics in the CLI, review the exclusions and explicitly set `accept_common_sample` to `true` in a copy of the request.
