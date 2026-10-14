# SCD41／Pi 5：唯讀與 dry-run skill

**這不是已啟用的 AI 控制器。永遠不會送出輸出指令，`--execute` 一律拒絕。**

依 Jeff 2026-10-14 的實際安裝紀錄與保存的 GET API 報告，重新撰寫上游 Setasoma `mycodo-hermes-skill` 架構；不沿用 shell 控制入口、不做 GPIO／SSH 呼叫、不安裝排程。只有 A 箱裝設備，B 箱為每日人工觀察的被動對照組，永遠不控制。

## 前置條件

Python 3.10+、標準函式庫即可，無須 pip、PyYAML、curl、jq、InfluxDB token 或套件安裝。此版本於 Windows Python 3.14.7 驗證。從專案根目錄執行，不必安裝到 Hermes。程式不呼叫 LLM；Hermes 只解讀 JSON 結果。

## 離線操作（不連 Pi）

```console
python -m unittest discover -s tests -v
python -m mycodo_scd41 replay --report fixtures/recorded-report.json --config config.example.json
python -m mycodo_scd41 simulate --fixture fixtures/offline-test.json
python -m mycodo_scd41 replay --report fixtures/recorded-report.json --audit runtime/audit.jsonl --html runtime/report.html
```

寫報告前自行建立 `runtime` 目錄。`--audit` 與 `--html` 為選填，路徑由操作者指定。JSON 輸出使用 stdout；不使用字串拼接 shell。離線模擬明確標示 **OFFLINE TEST ONLY NOT CURRENT PI DATA**，其中所有數字只是測試值，絕不可當成作物參數。

`replay` 保留每個量測的原始 epoch 時間，不把保存資料改標成「現在」。預設 freshness 尚未確認，因此顯示 `freshness_unconfigured`；設定已核准 freshness 後，過期資料為 `stale` 並阻擋計畫。JSON 的 `planned_commands` 與 `executed_commands` 分開，後者永遠為空。

## 未來需要時才使用的唯讀功能

**本次建置未呼叫任何硬體網路。** `read` 已實作，但尚未做現場 TLS／API 整合測試。取得操作者同意後才能執行：

```console
python -m mycodo_scd41 read --url https://your-pi.example --ca-pem trusted-ca.pem --config config.example.json
```

API key 由遮罩 `getpass` 輸入，或由執行環境的 `MYCODO_API_KEY` 讀取；無 API key 命令列參數、不把 key 存檔或放進報告。CA PEM 必須由操作者確認來源；預設使用系統信任鏈，驗證主機名與憑證。沒有 `--insecure`、`curl -k` 或跳過 TLS 的選項。禁止 HTTP、URL 帳密、query、fragment、非根路徑；拒絕重新導向，避免把認證送往別處。Mycodo v8.17.0 的 `X-API-KEY` 需 base64 編碼，程式依已檢查的官方原始碼處理。

固定 GET allowlist：

- `/api/settings/inputs`
- `/api/settings/device_measurements/by_device_id/{input_uuid}`
- `/api/outputs/`
- `/api/measurements/last/{input_uuid}/{unit}/{channel}/600`

600 秒只是 API 查詢回溯範圍，**不是核准的安全 freshness**。不直接查 Flux；實際 InfluxDB 版本未確認，不聲稱版本或進行遷移。

## 實際設備與限制

- 輸入：`e0fe890e-dce7-4b14-9395-5b7815423e51`；SCD4x_CIRCUITPYTHON、I²C bus 1、0x62、每 60 秒。
- CH0 CO₂ ppm；CH1 溫度 C；CH2 濕度 percent；CH3 露點 C；CH4 VPD Pa。
- SCD41 溫度偏移 4.0、self calibration false：只記錄、不更改，也不重複扣除偏移。
- 霧化器 GPIO5：`bf9acc8f-76e6-4d3e-8f24-1f9a38512d24`。
- 風扇 GPIO16：`1a58c7c4-481a-408c-b1bc-d88f6ba75b10`。
- 兩者 channel 0、pinctrl、HIGH 開啟，startup/shutdown OFF。沒有 SHT45、相機、多工器或繼電器控制鏈。
- 輸出 channel 必須依 `output_id` 與裝置 UUID 相接，不能按陣列位置猜。保存報告省略 `output_id`，不能由它重建可靠關聯；未知狀態保持 `unknown`。
- 菇種「袖珍菇／秀珍菇」待供應商確認，所有溫濕度、CO₂ 門檻及最大 pulse、冷卻、freshness 均為 null；approved false、provenance null。未設定時不稱環境「正常」。
- 完整核准參數、有限數值、新鮮時間戳才可產生離線計畫；布林、非有限數字、無效／未來／過期時間及缺欄位阻擋。溫度超核准範圍、非物理 RH／CO₂／VPD 同樣阻擋。
- 加濕還要明確水量確認、已知最後加濕時間與足夠冷卻。沒有水位感測器，預設水量未知；設定中的人工確認不是硬體聯鎖。

## 文件與已知缺口

- `SKILL.md`：Hermes 操作規則。
- `docs/future-control-checklist.md`：未來控制前不可略過的人工核准與 Pi 保護。
- `THIRD_PARTY/NOTICE.md`、`THIRD_PARTY/upstream-LICENSE`：上游來源、commit、MIT 授權。
- `docs/TDD-record.md`：逐一 RED→GREEN 的實際執行紀錄。

安全範圍是「無致動能力」，不是完備的實體控制安全證明。尚無現場憑證整合、可靠 water interlock、Pi 本地 cutoff／Functions、持久化冷卻、並行鎖與時限 API 驗證。未安裝排程；GitHub 保存程式碼不等於已部署到 Hermes 或樹莓派。JSONL 只保存 UTC 時間、狀態、計畫數、執行數與錯誤存在旗標，不保存原始錯誤字串或資料。

安全回歸測試共 24 項：包含未知命令列參數不回顯、極大整數讀值拒絕，以及 API 布林輸出狀態的正確保存。仍不得在命令列輸入 API key。Audit 尚未細分錯誤代碼；現場整合與真實控制仍未啟用。
