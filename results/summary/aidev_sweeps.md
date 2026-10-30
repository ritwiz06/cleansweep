# AIDev sweeps

100 reports on 20 of the 20 runnable repos used (1 excluded), at their head sha; 2 repos without an agent scope are summarized at the end; not yet complete: none. Agent scope: lines and files that agent pull requests wrote (first-parent blame). Applied files = deleted files; applied code = every other applied edit, of which applied_format and applied_import are format and unused-import edits; lines_removed_code = net lines removed by the other applied edits (per run, at least 0). Could not apply = the edit tool could not make the change (e.g. a dependency listed in pyproject.toml). Hidden checked = runs whose diff applied in a workspace with second-model tests; hidden_deleted = changes where every changed test uses a function, class or file the cleanup deleted; hidden_behavior = any other change.

| method | repos | applied_files | applied_code | files_removed | lines_removed | applied_format | applied_import | lines_removed_code | rolled_back_compile | rolled_back_tests | rolled_back_ast | rolled_back_probes | could_not_apply | hidden_checked | hidden_changed | hidden_deleted | hidden_behavior | llm_retries | llm_failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cleansweep-gatekeeper | 20 | 1 | 192 | 1 | 592 | 126 | 1 | 1295 | 3 | 7 | 0 | 0 | 87 | 19 | 3 | 3 | 0 | 0 | 10 |
| cleansweep-advisory | 20 | 1 | 235 | 1 | 1723 | 126 | 1 | 2433 | 4 | 32 | 0 | 7 | 126 | 19 | 3 | 3 | 0 | 2 | 8 |
| guard_tests_only | 20 | 1 | 235 | 1 | 1811 | 126 | 1 | 2578 | 4 | 35 | 0 | 0 | 130 | 19 | 4 | 3 | 1 | 0 | 6 |
| tools_only | 20 | 0 | 114 | 0 | 1734 | 0 | 15 | 2345 | 0 | 0 | 0 | 0 | 0 | 19 | 4 | 4 | 0 | 0 | 0 |
| one_shot_llm | 20 | 46 | 36 | 46 | 6496 | 0 | 0 | 6605 | 0 | 0 | 0 | 0 | 0 | 19 | 2 | 1 | 1 | 0 | 0 |

## Items by category

lines_net: lines deleted minus lines added by the applied edits. tools_only makes one ruff-fixes edit per run (ruff F401 --fix, then ruff format on the files agent commits created), listed under unused_import.

| method | category | proposed | safe_lane | applied | lines_net | rolled_back | could_not_apply |
|---|---|---|---|---|---|---|---|
| cleansweep-gatekeeper | dead_code | 268 | 58 | 49 | 1063 | 4 | 5 |
| cleansweep-gatekeeper | duplicate | 168 | 9 | 1 | 9 | 5 | 3 |
| cleansweep-gatekeeper | format | 126 | 126 | 126 | -1719 | 0 | 0 |
| cleansweep-gatekeeper | leftover_file | 2 | 2 | 1 | 142 | 1 | 0 |
| cleansweep-gatekeeper | other | 63 | 0 | 0 | 0 | 0 | 0 |
| cleansweep-gatekeeper | security | 12 | 0 | 0 | 0 | 0 | 0 |
| cleansweep-gatekeeper | unused_dependency | 125 | 94 | 15 | 81 | 0 | 79 |
| cleansweep-gatekeeper | unused_import | 1 | 1 | 1 | 1 | 0 | 0 |
| cleansweep-advisory | dead_code | 268 | 121 | 87 | 2147 | 20 | 14 |
| cleansweep-advisory | duplicate | 168 | 30 | 3 | 63 | 21 | 6 |
| cleansweep-advisory | format | 126 | 126 | 126 | -1719 | 0 | 0 |
| cleansweep-advisory | leftover_file | 2 | 2 | 1 | 142 | 1 | 0 |
| cleansweep-advisory | other | 66 | 0 | 0 | 0 | 0 | 0 |
| cleansweep-advisory | security | 12 | 0 | 0 | 0 | 0 | 0 |
| cleansweep-advisory | unused_dependency | 125 | 125 | 18 | 81 | 1 | 106 |
| cleansweep-advisory | unused_import | 1 | 1 | 1 | 1 | 0 | 0 |
| guard_tests_only | dead_code | 268 | 121 | 84 | 2235 | 23 | 14 |
| guard_tests_only | duplicate | 168 | 30 | 6 | 120 | 14 | 10 |
| guard_tests_only | format | 126 | 126 | 126 | -1719 | 0 | 0 |
| guard_tests_only | leftover_file | 2 | 2 | 1 | 142 | 1 | 0 |
| guard_tests_only | other | 66 | 0 | 0 | 0 | 0 | 0 |
| guard_tests_only | security | 12 | 0 | 0 | 0 | 0 | 0 |
| guard_tests_only | unused_dependency | 125 | 125 | 18 | 81 | 1 | 106 |
| guard_tests_only | unused_import | 1 | 1 | 1 | 1 | 0 | 0 |
| tools_only | dead_code | 250 | 250 | 99 | 2345 | 0 | 0 |
| tools_only | unused_import | 20 | 20 | 15 | -1603 | 0 | 0 |
| one_shot_llm | other | 83 | 83 | 82 | 6605 | 0 | 0 |

## Runs with over 100 applied edits

Applied edits / net lines removed per category (negative: lines added). Repos without an agent scope included.

| repo | method | applied | format | unused_import | dead_code | duplicate | leftover_file | other | lines_removed |
|---|---|---|---|---|---|---|---|---|---|
| PytorchConnectomics/pytorch_connectomics | cleansweep-gatekeeper | 292 | 268 / -4511 | 3 / 3 | 14 / 377 | 0 / 0 | 0 / 0 | 7 / 36 | 0 |

## Hidden changes

| repo | method | changed_tests | cause | deleted_code_used |
|---|---|---|---|---|
| PytorchConnectomics/pytorch_connectomics | guard_tests_only | 1 | behavior |  |
| Usagi-org/ai-goofish-monitor | one_shot_llm | 84 | behavior | FailureGuard, SkipDecision, add_json_response_format, add_json_text_format ... |
| eric-tramel/slop-guard | tools_only | 1 | deleted code | _select_fit_samples |
| eric-tramel/slop-guard | one_shot_llm | 22 | deleted code | benchmark_rules, build_lengths, build_word_stream, compose_text ... |
| gotalab/skillport | cleansweep-gatekeeper | 4 | deleted code | create_skills_table, format_score, no_results_panel |
| gotalab/skillport | cleansweep-advisory | 4 | deleted code | create_skills_table, format_score, no_results_panel |
| gotalab/skillport | guard_tests_only | 4 | deleted code | create_skills_table, format_score, no_results_panel |
| gotalab/skillport | tools_only | 4 | deleted code | create_skills_table, format_score, no_results_panel |
| thomasjjj/Telegram-Snowball-Sampling | cleansweep-gatekeeper | 27 | deleted code | remove_inaccessible_channels, sanitize_filename, split_search_terms |
| thomasjjj/Telegram-Snowball-Sampling | cleansweep-advisory | 27 | deleted code | remove_inaccessible_channels, sanitize_filename, split_search_terms |
| thomasjjj/Telegram-Snowball-Sampling | guard_tests_only | 27 | deleted code | remove_inaccessible_channels, sanitize_filename, split_search_terms |
| thomasjjj/Telegram-Snowball-Sampling | tools_only | 27 | deleted code | remove_inaccessible_channels, sanitize_filename, split_search_terms |
| yusufkaraaslan/Skill_Seekers | cleansweep-gatekeeper | 23 | deleted code | find_blocks_by_type, find_code_by_language, find_tables_by_caption, get_argument_help ... |
| yusufkaraaslan/Skill_Seekers | cleansweep-advisory | 23 | deleted code | find_blocks_by_type, find_code_by_language, find_tables_by_caption, get_argument_help ... |
| yusufkaraaslan/Skill_Seekers | guard_tests_only | 23 | deleted code | find_blocks_by_type, find_code_by_language, find_tables_by_caption, get_argument_help ... |
| yusufkaraaslan/Skill_Seekers | tools_only | 17 | deleted code | add_rag_arguments, get_argument_help, get_behavior_argument_names, get_common_argument_names ... |

## Second-model hidden tests (glm-5-3), per repository

| repo | test_files | stable_tests | passing | unstable |
|---|---|---|---|---|
| 567-labs/instructor | 6 | 58 | 38 | 0 |
| FangYuan33/easy-code-reader | 3 | 25 | 24 | 0 |
| Human-Agent-Society/CORAL | 6 | 111 | 98 | 0 |
| PytorchConnectomics/pytorch_connectomics | 4 | 72 | 62 | 0 |
| Usagi-org/ai-goofish-monitor | 6 | 84 | 78 | 0 |
| brentyi/tyro | 3 | 43 | 31 | 0 |
| commaai/opendbc | 1 | 34 | 34 | 0 |
| curvedinf/wove | 6 | 44 | 37 | 0 |
| eric-tramel/slop-guard | 6 | 68 | 59 | 0 |
| gotalab/skillport | 3 | 46 | 44 | 0 |
| marin-community/haliax | 5 | 116 | 111 | 0 |
| posit-dev/chatlas | 4 | 33 | 25 | 0 |
| shotgun-sh/shotgun | 5 | 78 | 57 | 0 |
| strawberry-graphql/strawberry | 2 | 24 | 24 | 0 |
| thomasjjj/Telegram-Snowball-Sampling | 5 | 48 | 44 | 0 |
| trailofbits/dropkit | 4 | 61 | 58 | 0 |
| utensils/mcp-nixos | 1 | 6 | 5 | 0 |
| wkentaro/imgviz | 6 | 73 | 69 | 0 |
| yusufkaraaslan/Skill_Seekers | 4 | 70 | 69 | 0 |

## Repos without an agent scope (not in the tables above)

No agent commit in the recorded history, so the detectors ran on the whole repository.

| method | repos | applied_files | applied_code | files_removed | lines_removed | applied_format | applied_import | lines_removed_code | rolled_back_compile | rolled_back_tests | rolled_back_ast | rolled_back_probes | could_not_apply | hidden_checked | hidden_changed | hidden_deleted | hidden_behavior | llm_retries | llm_failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cleansweep-gatekeeper | 1 | 0 | 292 | 0 | 0 | 268 | 3 | 413 | 0 | 0 | 0 | 0 | 10 | 1 | 1 | 1 | 0 | 0 | 1 |
| tools_only | 1 | 0 | 21 | 0 | 0 | 0 | 1 | 1039 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 |
| one_shot_llm | 1 | 1 | 1 | 1 | 32 | 0 | 0 | 32 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
