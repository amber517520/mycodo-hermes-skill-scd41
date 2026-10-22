# 垂直 TDD 與離線驗證紀錄

每個完成的功能切片先新增一個 unittest 方法，執行該方法確認 FAIL，再實作最小功能並執行全套確認 OK，然後才新增下一個方法。網路邊界以本地 fake／mock 代替，沒有硬體連線。

| 次序 | 新增測試／切片 | 實際 RED | 實際 GREEN 全套數 |
|---|---|---|---|
| 1 | default_configuration_is_unapproved | FAIL，缺 default_config | 1 |
| 2 | configuration_allowlist_cannot_be_changed | FAIL，缺 validate_config | 2 |
| 3 | reading_validation_fails_closed | FAIL，缺 reading_status | 3 |
| 4 | unconfigured_evaluation_shows_readings_without_plans | FAIL，缺 evaluate | 4 |
| 5 | approved_complete_fresh_fixture_plans_only | FAIL，unconfigured 非 ready | 5 |
| 6 | partial_or_invalid_approval_blocks_plans | FAIL，反向／非法門檻仍計畫 | 6 |
| 7 | humidifier_requires_water_and_cooldown_confirmation | FAIL，水量／冷卻未知仍計畫 | 7 |
| 8 | out_of_range_environment_blocks_all_plans | FAIL，異常環境仍計畫 | 8 |
| 9 | replay_keeps_original_measurement_timestamps | FAIL，缺 replay | 9 |
| 10 | output_mapping_uses_output_uuid_not_array_index | FAIL，缺 map_outputs | 10 |
| 11 | https_client_rejects_unsafe_urls_and_redirects | FAIL，缺 ReadClient | 11 |
| 12 | get_client_sanitizes_failure_and_enforces_size_limit | FAIL，超大合法 JSON 未拒絕 | 12 |
| 13 | read_snapshot_collects_only_get_inventory_and_channels | FAIL，缺 read_snapshot | 13 |
| 14 | reports_escape_html_and_remove_nonfinite_numbers | FAIL，缺報告函式 | 14 |
| 15 | audit_omits_untrusted_errors_credentials_and_payloads | FAIL，缺 write_audit | 15 |
| 16 | cli_execute_is_rejected_before_reading_files | FAIL，CLI 尚無 entrypoint | 16 |
| 17 | cli_replay_is_offline_and_keeps_old_times | FAIL，replay 尚未支援 | 17 |
| 18 | cli_simulation_requires_explicit_test_fixture | FAIL，simulate 尚未支援 | 18 |
| 19 | cli_emits_optional_audit_and_escaped_html | FAIL，報告參數尚未支援 | 19 |
| 20 | cli_read_uses_masked_key_and_get_only_client | FAIL，read 尚未支援 | 20 |
| 21 | cli_configuration_can_never_enable_execute | FAIL，config 尚未支援 | 21 |

初始工具曾把完整檔案 read 誤判為部分 view 而拒絕 overwrite，因此改用具目標字串的 patch；該工具失敗與一次缺測試方法的 loader error 不算 RED。正式切片均重新得到預期 assertion failure 後才實作。

後續再完成 3 項強化測試：未知命令列參數不回顯、極大整數讀值拒絕，以及 API 布林輸出狀態保存，因此目前總數為 24 項。Audit 細分錯誤代碼仍屬未完成項目。

## 最終真實執行

命令：`python -m unittest discover -s tests -v`

最新實際回傳：`Ran 24 tests`，`OK`，exit code 0。

- `simulate --fixture fixtures/offline-test.json`：ready，2 個離線計畫，0 個執行；明確標示 synthetic TEST，不是 Pi 現在資料。
- `replay --report fixtures/recorded-report.json --config config.example.json`：unconfigured，5 個讀值保留原始時間，0 個計畫、0 個執行。
- 對 operator 完整 stage2 報告與 curated fixture 做程式比較：5 個 reading dict 完全相同，包括 timestamp。用已核准的 **TEST** freshness 在真正目前時間評估，5 個全為 stale，計畫與執行均 0。
- `config.example.json` 與程式 default_config 完全相同；上游 MIT license 內容相同；SKILL 起始 frontmatter、description 長度與句點確認通過。
- TLS／HTTP 成功現場連線未測試；client 單元測試沒有發網路請求。

已知缺口見 README 與 future-control-checklist；不能把 24 個測試通過解讀為可用於實體自動控制。
