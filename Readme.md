這份清單對應你目前最新的 agent_prototype.py。
# 缺口一：真實 LLM API 串接
位置： get_structured_llm_analysis 函數內

## 需要刪除：用來測試的「假邏輯」：

```
# [模擬 API 回傳]：依據新聞是否有內容給予不同的隨機感分數
if "無相關" in news_content or "失敗" in news_content:
    raw_output = '{"score": 50, "explanation": "缺乏新聞資訊，給予中立評價。"}'
else:
    raw_output = '{"score": 75, "explanation": "近期有相關市場動態，可能帶動波段行情。"}'
```


## 需要補上：
把申請好的 Google Gemini 或 OpenAI 的 API 呼叫程式碼註解打開，讓真實模型去閱讀上方抓到的 news_content，並將回傳的 JSON 格式字串存入 raw_output 變數。

# 缺口二：真實匯率資料 (TWD)

位置： 每日執行腳本區塊（第 191～192 行）

## 需要刪除：寫死的假匯率

```
FX_TODAY = 32.5
FX_YESTERDAY = 32.0
```


## 需要補上：
寫一段類似抓道瓊的爬蟲（例如使用 yfinance.Ticker("TWD=X")），抓取今日與昨日的真實台幣匯率，並賦值給 FX_TODAY 與 FX_YESTERDAY。

# 缺口三：競賽 150 檔股票池與動能
## 需要刪除：這 3 檔測試名單：

```
allowed_150_stocks = [
    {"id": "2330.TW", "momentum": 3, "current_price": 1000},
    {"id": "2454.TW", "momentum": -2, "current_price": 1100},
    {"id": "3231.TW", "momentum": 1, "current_price": 120}
]
```
## 需要補上：
寫一段迴圈去讀取主辦單位提供的 150 檔股票清單，用 API 批次抓取最新的收盤價與趨勢（動能指數），然後存成同樣格式的列表。