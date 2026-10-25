# Current Board（電流看板）— Spec v3

狀態：v3.2，2026-10-25。階段 1 已實作（分類法、名單、來源、抽取、資料模型、雙語報告與儀表板、白名單發佈、分析師指令）。取代 v2（docs/SPEC.md）。
主題：AI 電力與基礎設施全價值鏈（黃仁勳「五層蛋糕」的電力與基礎設施層）。
語言：儀表板與週報皆中英雙語。

---

## 0. 品牌

| 層級 | 名稱 | 中文 | 說明 |
|---|---|---|---|
| 母品牌 | **Current Board** | 電流看板 | current 同時是電流、資金流、時事；board 是配電盤、儀表板、看板 |
| 副標 | The power behind AI, on one board. | AI 背後的電，一板看盡。 | 永遠跟著名稱出現 |
| 主 slogan | **Follow the current.** | **跟著電流走。** | 改寫 follow the money |
| 首屏副標 | Who powers AI, who pays, and why now. | 誰供電、誰付錢、為什麼是現在。 | 分析師的三問 |
| 信任主張 | Every line on the board has a source. | 板上每一條都有來源。 | 週報與儀表板頁尾 |
| 週報 | **On the Board** | 本週上板 | reports/<week>.md |
| 月度論點 | Board Memo | 看板備忘 | 第 3 節的月度產物 |
| 關係表 | **Circuits** | 電路圖 | relations 表的對外名稱 |
| 追蹤名單 | **The Panel** | 配電盤 | watchlist 的對外名稱 |
| 新創募資子品牌 | **Current Board · Sparks** | 火花 | v2 的募資追蹤功能 |
| 方法論頁 | How the board is wired | 接線圖 | 公開程式碼與來源說明 |

命名核實（2026-10-25）：無同名公司、產品、電子報；GitHub `currentboard` 未被使用。單獨的 Current 與 Current±（英國能源新聞）、
GE Current、Current（團隊儀表板）相鄰，因此**永遠使用兩個字、不縮寫**。帳號與網址用連寫 `CurrentBoard` / `current-board`。
正式經營前到美國、台灣、英國查第 35、41、42 類商標。

---

## 1. 使用者與他們的一週

### 1.1 維運者兼作者（你）

一個人。每週投入約 1 小時做判斷，不寫程式、不開資料庫。所有操作透過兩個介面：
編輯 YAML 檔，以及和 Claude Code 對話。

| 時間 | 你做什麼 | 系統做什麼 |
|---|---|---|
| 週一 08:00（自動） | 睡覺 | 抓新聞 → Claude 分類 → 對照合併 → 產出「待審清單」 |
| 週一上午，約 40 分 | 看待審清單 8–12 則；每則：讀原文、調整重要度、寫一句註記；決定候選公司收或不收 | 記錄你的每個決定與理由（分歧日誌） |
| 週一上午，約 15 分 | 口述三段「本週觀點」，Claude 起草，你修改 | 合成週報：上半部機器事實、下半部你的觀點 |
| 週一上午，約 5 分 | 說「發佈」 | 過濾白名單欄位 → 產出儀表板 → 推到公開倉庫；週報完整版留在私人倉庫 |
| 每月一次，約 30 分 | 讀分歧日誌，決定要不要改分類法、名單、評分規則 | 列出你和機器評分差距最大的訊號 |

你的核心動作只有三種：**評分**（這有多重要）、**取捨**（追不追這家）、**觀點**（所以呢）。
其餘都是機器的事。

### 1.2 觀眾（不定期、唯讀）

團隊同事、主管、或你分享連結給的外部人。打開一個網址，看到：

- 本週與近八週的訊號趨勢、價值鏈各層的熱度
- 可篩選的新聞列表（標題、來源、日期、分層、機器摘要）
- 重大交易表（購電合約、併購、資本支出、募資）
- 追蹤中的公司卡片（公開欄位）
- 關係圖：誰向誰買電、誰投資誰、誰供貨給誰

觀眾**看不到**：你的註記與觀點理由、重要度調整紀錄、分歧日誌、候選公司評分、投資人利益衝突評等、
名單中的 `notes` 欄位、任何未發佈的草稿。觀眾無法寫入任何東西，因為網頁是靜態檔案。

### 1.3 第三個角色：Claude（維運助手）

不是使用者，是你的操作介面。它能讀資料庫、改 YAML、跑管線、起草文字、記錄你的決定。
你對它說的話就是後台操作。所有寫入動作在執行前會告訴你要改什麼。

---

## 2. 從使用情境倒推出的需求

### 2.1 分類法：改成價值鏈（config/taxonomy.yaml）

`sub_verticals` 改名為 `value_chain`，代碼如下。每個代碼有 `label_zh` 與 `label_en`。

| 代碼 | 中文 | 英文 | 涵蓋 |
|---|---|---|---|
| `compute_demand` | 算力需求端 | AI Compute Demand | 超大規模業者、AI 實驗室、新型雲端業者的算力與電力需求、園區宣告 |
| `generation_nuclear` | 核能發電 | Nuclear Generation | 核電重啟、SMR、核燃料 |
| `generation_other` | 其他發電 | Gas, Fuel Cell & Onsite Power | 燃氣、燃料電池、現場發電、地熱 |
| `transmission_grid` | 輸配電與電網設備 | Transmission & Grid Equipment | 變壓器、開關設備、HVDC、併網排隊 |
| `storage` | 儲能 | Energy Storage | 電池儲能、長時儲能 |
| `dc_physical` | 資料中心實體層 | Data Center Power & Cooling | 配電、UPS、冷卻、模組化機房 |
| `dc_development` | 資料中心開發 | Data Center Development & REIT | 園區開發、不動產、土地與電力取得 |
| `offtake_markets` | 購電與市場 | PPAs, Offtake & Markets | 購電合約、容量市場、電價 |
| `energy_software` | 能源軟體 | Energy Software | VPP、預測、調度最佳化（v2 全部併入這層） |
| `policy_regulation` | 政策與監管 | Policy & Regulation | FERC、各國能源政策、出口管制 |
| `other` | 其他 | Other | |

`signal_types` 擴充：

| 代碼 | 中文 | 英文 |
|---|---|---|
| `funding` | 募資 | Funding |
| `m_and_a` | 併購 | M&A |
| `offtake` | 購電與長約 | PPA / Offtake |
| `capex` | 資本支出與建廠 | Capex & Buildout |
| `earnings` | 財報與財測 | Earnings & Guidance |
| `partnership` | 合作與客戶 | Partnership |
| `product` | 產品與技術 | Product & Technology |
| `supply_chain` | 供應鏈與產能 | Supply Chain & Capacity |
| `people` | 人事異動 | People |
| `regulatory` | 政策與法規 | Regulatory |
| `investor_thesis` | 投資人觀點 | Investor Thesis |
| `other` | 其他 | Other |

新增 `entity_types`：`hyperscaler`（雲端巨頭）、`ai_lab`（AI 模型公司）、`neocloud`（GPU 雲端與算力園區業者）、`public_company`（上市設備或能源公司）、`private_startup`、`utility`（公用事業與獨立發電商）、`investor`、`government`。

新增 `relation_types`：`buys_power_from`、`supplies_to`、`invests_in`、`acquires`、`partners_with`、`regulates`。

### 2.2 追蹤名單：對象分類型（config/watchlist.yaml）

每個對象有 `entity_type`（它是誰）與 `value_chain`（它在價值鏈的主要位置）。首批建議如下，**由你增刪**。
`notes` 欄位是你的，永不公開、永不被機器覆寫。

| 對象 | entity_type | value_chain | 為什麼追 |
|---|---|---|---|
| OpenAI | ai_lab | compute_demand | Stargate 園區、與 Oracle / SoftBank / 微軟的算力與電力承諾 |
| Anthropic | ai_lab | compute_demand | 與 Google、Amazon 的算力協議，資料中心投資宣告 |
| xAI | ai_lab | compute_demand | Colossus 自建園區、燃氣機組現場發電，是「AI 實驗室直接買電」的極端案例 |
| Microsoft、Google、Amazon、Meta、Oracle | hyperscaler | compute_demand | 需求端，每筆購電、資本支出、核電合約都是訊號 |
| CoreWeave、Crusoe、Nebius | neocloud | compute_demand | 新型算力業者，擴張速度與融資方式最激進 |
| NVIDIA | public_company | compute_demand | 生態系錨點，其投資與對電力的公開發言帶動整層敘事 |
| Constellation、Vistra、Talen、NextEra、Dominion | utility | generation_nuclear / offtake_markets | 供給端，核電重啟與長約的簽約方 |
| Oklo、NuScale、X-energy、Kairos Power | private_startup / public_company | generation_nuclear | SMR 與新核能 |
| Bloom Energy | public_company | generation_other | 燃料電池現場發電，繞過電網排隊 |
| GE Vernova、Siemens Energy | public_company | transmission_grid | 燃氣機組與電網設備，交期是瓶頸指標 |
| Vertiv、Schneider Electric、Eaton | public_company | dc_physical | 資料中心配電與冷卻 |
| Equinix、Digital Realty | public_company | dc_development | 資料中心不動產 |
| v2 名單中仍相關的能源軟體新創 | private_startup | energy_software | 保留 |

**機器能不能自動找出值得關注的公司？** 可以，但要說清楚它找的是什麼。

現有機制（v2 已有）：發現用關鍵字抓到的新聞裡，Claude 若判斷「這家公司值得追」且不在名單上，就進候選區；
同一家被多篇提到就累積分數；每週最多提三家給你。它找的是「最近在相關新聞裡頻繁出現且有融資」的公司。

v3 加三條偵測規則，讓它也能找到「策略上重要但不一定在募資」的對象：

1. **共現**：一家不在名單上的公司，四週內與三個以上追蹤對象同時出現在新聞中。
2. **關係對手方**：追蹤對象簽了購電、供貨、投資合約，對手方不在名單上，自動成為候選。
3. **加速度**：某公司的提及次數本月是上月的三倍以上。

機器的限制：它只能從你給的來源與關鍵字裡找，所以關鍵字沒覆蓋的角落它看不到；它判斷「出現頻率」而非「重要性」，
重要性是你的事。候選永遠是提案，收不收由你決定並寫理由。

### 2.3 資料模型：每個欄位的意義與誰負責

來源欄：**人** = 你在 YAML 或對話中決定；**機** = 管線或 Claude 抽取；**機→人** = 機器給初值、你可覆寫。
可見性：**公開** = 會出現在觀眾儀表板；**私有** = 永不離開私人倉庫。

**companies（追蹤對象）**

| 欄位 | 型別 | 意義 | 來源 | 可見性 |
|---|---|---|---|---|
| slug | 文字，主鍵 | 由名稱產生的識別碼，如 `constellation-energy` | 機 | 公開 |
| name | 文字 | 顯示名稱 | 人 | 公開 |
| domain | 文字 | 官網網域，當身分證用 | 人 | 公開 |
| aliases | 文字清單 | 新聞裡會出現的其他寫法，供比對 | 人（機可提案） | 公開 |
| entity_type | 代碼 | 它是誰：hyperscaler / ai_lab / utility… | 人 | 公開 |
| value_chain | 代碼 | 主要位置：compute_demand / generation_nuclear… | 人 | 公開 |
| ticker | 文字，可空 | 上市代號，之後接財報用 | 人 | 公開 |
| hq_country、region | 代碼 | 總部國家、區域（NA / EU / APAC） | 人 | 公開 |
| status | 代碼 | active / paused / dropped | 人 | 公開 |
| notes | 長文字 | 你的分析筆記 | 人 | **私有** |

**signals（每一則新聞）**

| 欄位 | 型別 | 意義 | 來源 | 可見性 |
|---|---|---|---|---|
| url、resolved_url | 文字 | 原始與解開轉址後的連結，`url` 唯一 | 機 | 公開 |
| title、source、published_at | 文字、時間 | 標題、媒體、發布時間 | 機 | 公開 |
| body | 長文字 | 全文，給 Claude 讀，最多 6000 字 | 機 | 私有（版權，只公開連結） |
| scope、query | 代碼、文字 | 由哪類查詢抓到：company / investor / discovery | 機 | 公開 |
| status | 代碼 | new / extracted / failed | 機 | 私有 |
| relevant | 布林 | 是否與主題相關 | 機→人 | 公開 |
| signal_type | 代碼 | 募資、購電、資本支出、財報… | 機→人 | 公開 |
| value_chain | 代碼 | 這則新聞主要落在哪一層 | 機→人 | 公開 |
| importance | 整數 1–5 | 機器評分；你的覆寫存在 analyst_notes | 機 | 公開（顯示機器分） |
| summary_zh、summary_en | 文字 | 一到兩句雙語摘要 | 機 | 公開 |
| deal_value_usd | 數字，可空 | 交易、合約、資本支出的美元估值 | 機 | 公開，標示「估計」 |
| capacity_mw | 數字，可空 | 涉及的電力容量 | 機 | 公開 |
| counterparties | 文字清單 | 新聞中提到的所有對象名稱（含不在名單上的） | 機 | 公開 |
| extracted_json | JSON | Claude 的完整原始回答，供追溯 | 機 | 私有 |

**relations（誰跟誰做了什麼）**

| 欄位 | 型別 | 意義 | 來源 | 可見性 |
|---|---|---|---|---|
| subject_slug、object_slug | 文字 | 主體與客體，如 Microsoft → Constellation | 機→人 | 公開 |
| relation_type | 代碼 | buys_power_from / supplies_to / invests_in / acquires / partners_with | 機→人 | 公開 |
| value_usd、capacity_mw、term_years | 數字，可空 | 金額、容量、年限 | 機 | 公開，標示「估計」 |
| signal_id | 外鍵 | 來源新聞，每條關係都要有出處 | 機 | 公開（連到來源連結） |
| confidence | 0–1 | Claude 對這條關係的信心 | 機 | 公開 |
| first_seen、last_seen | 時間 | 第一次與最近一次被提到 | 機 | 公開 |

**analyst_notes（你對單則訊號的判斷）**

| 欄位 | 型別 | 意義 | 來源 | 可見性 |
|---|---|---|---|---|
| signal_id | 外鍵 | 哪一則 | 人 | 私有 |
| importance_override | 整數 1–5，可空 | 你的評分，取代機器分 | 人 | 私有（週報完整版用你的分） |
| note_zh、note_en | 文字 | 你的一句判斷 | 人（Claude 可翻譯） | 私有，可選擇放進公開週報 |
| deal_logic | 結構化文字 | 第 3 節的五問答案（可空） | 人 | 私有 |
| decided_at | 時間 | | 機 | 私有 |

**decision_log（分歧日誌）**

| 欄位 | 型別 | 意義 | 來源 | 可見性 |
|---|---|---|---|---|
| kind | 代碼 | score（改評分）/ candidate（收或不收）/ watchlist（改名單）/ taxonomy（改分類） | 機 | 私有 |
| target | 文字 | 哪則訊號、哪家公司、哪個代碼 | 機 | 私有 |
| machine_value、human_value | 文字 | 機器原本怎麼說、你改成什麼 | 機 / 人 | 私有 |
| reason | 文字 | 你的理由，一句即可 | 人 | 私有 |

**weekly_views（週報觀點）**

| 欄位 | 型別 | 意義 | 來源 | 可見性 |
|---|---|---|---|---|
| week | 文字，主鍵 | ISO 週，如 2026-W44 | 機 | |
| draft_zh、draft_en | 長文字 | 三段觀點草稿 | 人口述、Claude 起草、人定稿 | 私有；你決定是否放進公開版 |
| published_at | 時間 | 發佈時間 | 機 | |

**candidates（候選公司）**：name、domain、value_chain、why_relevant、mentions、score 由機器產生，`status`（proposed / accepted / rejected）由你決定。
`score` 與 `why_relevant` 私有，其餘在你接受後才公開。

**runs**：每次管線執行的時間與統計，機器寫，私有。

### 2.4 抽取（radar/extract.py）

Claude 的回答格式新增：`value_chain`、`entity_type`（每個提到的對象）、`deal_value_usd`、
`capacity_mw`、`relations[]`（主體、客體、關係類型、金額、年限）、`summary_zh`、`summary_en`。

重要度 1–5 的評分尺，寫進提示詞，之後依分歧日誌修訂：

- 5：改變價值鏈某一層供需結構的事件（GW 級購電、核電重啟、州級政策首例、十億美元級併購）
- 4：主要玩家的具體承諾（資本支出數字、新廠、長約）
- 3：有名字有金額的一般交易、產品發表
- 2：評論、分析、重述
- 1：邊緣相關

### 2.5 資料來源升級（config/sources.yaml）

| 來源 | 用途 | 第幾階段 |
|---|---|---|
| Google News RSS，每個追蹤對象一句 | 對象訊號 | 現有 |
| Google News RSS，主題關鍵字改為價值鏈各層 | 發現 | 第 1 階段改關鍵字 |
| Data Center Dynamics、Utility Dive、Data Center Frontier RSS | 發現 | 第 1 階段 |
| CTVC、Canary Media、Latitude Media RSS | 發現 | 現有 |
| SEC EDGAR 8-K（重大合約、併購）與 10-Q 資本支出 | 上市公司事實 | 第 3 階段 |
| 超大規模業者官方部落格 RSS | 購電與園區公告 | 第 2 階段 |
| FERC / DOE 公告頁 | 政策 | 第 3 階段 |

### 2.6 待審清單（每週 1 小時的關鍵）

機器每週只把以下訊號放進待審清單，目標 8–12 則：

1. 重要度 ≥ 4 的全部
2. 重要度 3 且有金額或 MW 數的
3. 新出現的關係（第一次看到 A 向 B 買電）
4. 候選公司（最多 3 家）

其餘訊號留在資料庫、進儀表板，但不佔你的時間。

### 2.7 兩個介面、兩個倉庫、一道白名單

**觀眾看的介面**：一個公開網址（GitHub Pages，例如 `https://<你的帳號>.github.io/venture-radar/`）。
它是一個靜態 HTML 檔，由機器從公開欄位產生。觀眾看到趨勢圖、新聞列表、交易表、公司卡片、關係圖。
網頁沒有登入、沒有後端、沒有資料庫連線，所以沒有任何可以「改」或「侵入」的路徑；
唯一的風險是「網頁裡放了不該放的資料」，白名單就是為了這件事。

**你看的介面**，有三個，都在你自己的電腦上：

1. **VS Code + Claude Code 對話**：所有「寫入」動作在這裡。改名單、評分、寫註記、起草觀點、發佈，用說的。
2. **私人工作台頁面**（`workbench.html`）：每週一機器產生一頁本機 HTML，列出待審的 8–12 則，
   每則有標題、來源連結、機器摘要、機器評分、相關對象、過去對這家公司的註記。
   你在瀏覽器裡打開它閱讀，決定好了回到對話說「第 3 則改 5 分」。它只是給你看的清單，不會部署、不在倉庫裡。
3. **週報完整版**（`reports/<週>.md`）：Markdown，在 VS Code 按預覽讀。上半部機器事實、下半部你的觀點。存在私人倉庫。

**白名單是什麼**：一份寫在程式裡的清單，列出「允許出現在公開網頁的欄位」。2.3 每張表標「公開」的欄位就是白名單。
產生儀表板時，程式只拿白名單欄位；產生完後再掃一次輸出檔，若出現任何私有欄位名稱（`notes`、`importance_override`、
`reason`、`deal_logic`…）或你的註記文字，發佈中止。這是一道自動檢查，不靠人記得。

**兩個倉庫**（兼顧作品集與隱私）：

| 倉庫 | 公開/私人 | 內容 | 作用 |
|---|---|---|---|
| `venture-radar` | 公開 | `radar/` 程式、`tests/`、範本、`config/examples/` 示範名單、`docs/` 規格與說明、`gh-pages` 分支上的儀表板 | 作品集：別人能看到你怎麼設計、怎麼寫，也能拿去追自己的主題 |
| `venture-radar-data` | 私人 | 真實 `config/`、`data/radar.db`、`reports/`、`workbench.html` | 你的研究內容與判斷 |

程式透過環境變數 `RADAR_DATA_DIR` 知道資料在哪。本機兩個資料夾並排；GitHub Actions 跑的時候 checkout 兩個倉庫。

**資安保障清單**：

- 公開網頁是靜態檔，沒有可攻擊的後端；觀眾無法寫入。
- 私有資料在另一個私人倉庫，物理上不在公開倉庫裡，不是靠「記得不要 commit」。
- 白名單加發佈前自動掃描，擋住「程式改錯把私有欄位帶出去」。
- API key 只在本機 `.env`（被 .gitignore 排除）與 GitHub Secrets；程式碼中沒有任何金鑰。
- GitHub 帳號開雙因素驗證；私人倉庫不加協作者。
- 公開倉庫的 `config/examples/` 是示範名單，不是真名單。
- 新聞全文（`body`）不公開，只公開連結，避免版權問題。

### 2.8 介面：對話即後台

不另寫管理網頁。你對 Claude 說話，Claude 執行對應指令並先顯示將要改的內容。對照表：

| 你說 | Claude 執行 | 寫到哪 |
|---|---|---|
| 「這週待審清單」 | `radar review` | 讀取；規則在 sources.yaml 的 review 段 |
| 「#123 改 5 分，註記：…，理由：…」 | `radar note 123 --importance 5 --zh "…" --reason "…"` | analyst_notes + decision_log |
| 「#124 不相關」 | `radar note 124 --irrelevant --reason "…"` | analyst_notes + decision_log |
| 「#123 的五問：…」 | `radar note 123 --logic "…"` | analyst_notes.deal_logic |
| 「候選公司」 | `radar candidates` | 讀取（含評分、理由、哪條規則提的） |
| 「收 Holtec，上市公司，核能層」 | `radar accept "Holtec International" --entity-type public_company --value-chain generation_nuclear --reason "…"` | watchlist.accepted.yaml + decision_log |
| 「不收 X」 | `radar reject "X" --reason "…"` | candidates + decision_log |
| 「起草本週觀點：…」 | Claude 寫雙語草稿到檔案，你改完後 `radar view --zh f.md --en f.md [--public]` | weekly_views |
| 「發佈」 | `radar report` → `radar dashboard` → 推送（階段 3 加上倉庫拆分） | reports/、docs/ |
| 「這個月的分歧」 | `radar log --days 35` | 讀取 decision_log |
| 「Dominion 加進名單」 | 直接編輯 watchlist.yaml，顯示 diff，下次 run 同步 | config |

---

## 3. 學習迴路：兩種判斷力

### 3.1 取捨判斷（什麼值得追）

- **分歧日誌是核心產物。** 每次你改機器的評分、否決它的候選、調整名單，都記下理由。
- **每月回顧**：讀日誌，找模式（例如「我一直調高亞洲訊號」、「我不在意 Series A 以下」）。
- **寫回機器**：把模式寫進 2.4 的評分尺與提示詞。機器逐月變成你的學徒。

### 3.2 交易邏輯判斷（這件事為什麼發生、對誰有利）

這才是分析師的本事，而且只能靠反覆練習。方法是對每週一到兩則重要度 5 的訊號做「五問」，寫進 `analyst_notes.deal_logic`：

| 問 | 在練什麼 | 例：微軟向 Constellation 買三哩島核電 20 年 |
|---|---|---|
| **1. 誰付錢給誰，為什麼是現在？** | 看懂時機與動機 | 微軟付長約溢價；因為併網排隊五年起跳，買現成核電比等新建快 |
| **2. 誰得利、誰受損？** | 看懂利益結構 | Constellation 鎖定 20 年現金流；當地公用事業失去一個大客戶；新建核電商得到價格參考 |
| **3. 它解決了價值鏈哪個瓶頸？** | 把事件放回系統 | 瓶頸不是發電量，是「可快速取得的穩定電力」 |
| **4. 反方怎麼說？** | 避免只看一面 | 核電重啟成本與時程常被低估；長約價格可能高於未來市場價 |
| **5. 我預測什麼、什麼時候能驗證？** | 讓判斷可被打分 | 預測十二個月內至少再出現兩筆超大規模業者與核電的長約 |

配套機制：

- **預測登記簿**：第五問的答案帶一個到期日，到期時 Claude 提醒你回頭看對錯。對錯都要寫一句為什麼。
- **Claude 當對手**：寫完五問後，要求 Claude「用最強的反方論點攻擊我的第一到第三問」，再修改。
  這是訓練的關鍵一步，因為單獨思考很難看到自己的盲點。
- **月度論點備忘**：每月把四週的五問收斂成一頁「我現在對這一層的看法」，與上月比，看自己的想法怎麼變。
- **對照專業分析**：一個月後搜尋同一事件的券商或產業分析，比對你的五問漏了什麼。這一步 Claude 可以代勞搜尋與摘要。
- **季度回測**：三個月前標 5 分的訊號，現在看來是否真的重要？標 2 分而被忽略的，有沒有後來變大？

節奏建議：第一個月只做第 1、2 問，第二個月加第 3、4 問，第三個月開始做預測。每週一到兩則就夠，重點是連續。

## 4. 時程：今天上架觀眾版，一週後第一篇週報

目標時程經評估可行，但有兩個前提只有你能完成：提供 `ANTHROPIC_API_KEY`，以及在 GitHub 建兩個倉庫並開啟 Pages。
今天上架的會是**v2 內容的「beta」版**（八家能源軟體新創、現有分類），一週後的第一篇週報則用 v3 分類法。

| 日期 | 內容 | 誰 | 完成判準 |
|---|---|---|---|
| **今天** | 你提供 API key；建公開倉庫 `venture-radar` 與私人倉庫 `venture-radar-data`，開啟 Pages 與 Secrets | 你 | 兩個空倉庫存在 |
| ~~今天~~ | 作者決定不趕上架，直接做 v3 | — | — |
| ✅ 2026-10-25 | 階段 1 完成：taxonomy 改價值鏈（11 層）、watchlist 37 個對象、sources 依類型與分層、extract 雙語加關係加金額/MW、資料庫遷移、雙語報告（私人/公開兩版）、雙語儀表板、白名單與洩漏檢查、analyst_notes/decision_log/weekly_views 三張表、review/note/view/candidates/log 指令、28 個測試 | Claude | 待：API key 到位後跑 90 天回填，驗證待審清單是否 8–12 則 |
| 下一步 | 階段 2 剩餘：本機工作台頁（workbench.html）、五問範本與預測登記簿的到期提醒、名單定稿 | Claude + 你 | 你用對話完整走過一次模擬流程 |
| **下週一** | 第一次正式週一流程：機器產待審清單，你評分、寫註記、口述觀點，發佈第一篇雙語週報與更新後的儀表板 | 你 + Claude | 公開版週報與儀表板上線 |
| 之後兩到四週 | 階段 4：relations 表與抽取、關係圖、EDGAR 8-K、超大規模業者部落格 | Claude | 關係圖有 20 條以上有來源的關係 |
| 之後 | 階段 5：Claude 排程代跑，週一早上待審清單自動送達 | Claude | 你週一只需開一個對話 |

**風險**：Google News 轉址解碼依賴非官方端點，壞掉時抽取品質下降但不中斷；90 天回填約數百則，
Claude 費用估計在幾美元內；GitHub Pages 首次啟用有時要等幾分鐘才生效。

## 5. 不做的事

- 不做多人寫入後台。第二位作者出現前，對話加 YAML 足夠。
- 不做即時警示。週更是刻意的，給判斷留時間。
- 不爬付費資料庫（Crunchbase、PitchBook）、不爬 LinkedIn。
- 不把金額當權威數字。`deal_value_usd` 是模型估計，引用前看來源。
