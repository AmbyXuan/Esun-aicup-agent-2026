import re
import json
import os
from datetime import datetime

# ==========================================
# 參數與權重設定 (依據玉山比賽限制與策略調整)
# ==========================================
WEIGHT_MACRO = 0.3    # 大盤斜率權重 (建議追蹤 NASDAQ 或 費半)
WEIGHT_STOCK = 0.3    # 個股動能權重
WEIGHT_LLM = 0.2      # LLM 質化判斷權重
WEIGHT_TWD = 0.2      # 台幣資金面權重 (判斷外資動向)

THRESHOLD_BUY = 70    # 買進門檻總分 (滿分100)
THRESHOLD_SELL = 65   # 賣出門檻總分 (對風險較敏感，寧可錯殺不願抱虧)

# ==========================================
# 輔助函數：各項因子的動態計算邏輯
# ==========================================
def extract_llm_score(llm_text):
    """【第 3 部分】動態解析 LLM 回傳文字中的信心分數"""
    match = re.search(r"信心分數[：:]\s*(\d+)", llm_text)
    if match:
        return int(match.group(1))
    return 50 # 若解析失敗，給予中立分數，避免程式崩潰

def evaluate_macro_slope(macro_current, macro_prev):
    """【第 1 部分】動態計算大盤斜率 (二階導數：加速度判斷)"""
    delta = macro_current - macro_prev
    buy_score = 50
    sell_score = 50
    
    if macro_current > 0:
        if delta < 0: # 漲得變慢 (高檔背離)
            buy_score = max(0, 50 - abs(delta) * 20)
            sell_score = min(100, 60 + abs(delta) * 30)
        else:         # 漲得快 (趨勢強勁，順勢而為)
            buy_score = min(100, 60 + delta * 30)
            sell_score = max(0, 40 - delta * 20)
    else:
        if delta > 0: # 跌得變慢 (落底反彈)
            buy_score = min(100, 60 + abs(delta) * 30)
            sell_score = max(0, 40 - abs(delta) * 20)
        else:         # 跌得變快 (恐慌殺跌，無情停損)
            buy_score = 10 
            sell_score = min(100, 60 + abs(delta) * 40) 
            
    return buy_score, sell_score

def evaluate_forex(twd_current, twd_prev):
    """【第 4 部分】判斷台幣匯率 (外資動向)"""
    if twd_current < twd_prev: # 台幣升值 (熱錢匯入)
        return {"buy": 80, "sell": 20}
    elif twd_current > twd_prev: # 台幣貶值 (熱錢撤出)
        return {"buy": 20, "sell": 80}
    return {"buy": 50, "sell": 50}

def evaluate_held_stock_sell(momentum_index, is_profitable):
    """【第 2 部分-賣】計算庫存個股的賣壓分數 (風險乘數基礎)"""
    sell_score = 50
    if momentum_index > 0:
        sell_score = 50 + (momentum_index * 5) # 連漲越多，乖離率越高，超買風險增加
    elif momentum_index < 0:
        sell_score = 50 + (abs(momentum_index) * 10) # 連跌，停損壓力急劇增加
        
    if is_profitable:
        sell_score += 15 # 只要有賺錢，停利賣壓增加 (把獲利放口袋)
    else:
        if momentum_index < 0:
            sell_score += 20 # 賠錢又連跌，無情停損加分 (控制 MDD)
            
    return max(0, min(100, sell_score))

def evaluate_unowned_stock_buy(momentum_index):
    """【第 2 部分-買】計算空手個股的買進分數"""
    if momentum_index > 0:
        return min(100, 50 + (momentum_index * 10)) # 順勢突破買進
    elif momentum_index < 0:
        return max(0, 50 - (abs(momentum_index) * 10)) # 弱勢股不碰
    return 50

# ==========================================
# 核心決策大腦 (雙軌制：買進軌道 vs 賣出軌道)
# ==========================================
def generate_trading_decision(stock_id, is_owned, macro_current, macro_prev, 
                              twd_current, twd_prev, momentum_index, 
                              llm_text, current_price=0, buy_price=0):
    
    macro_buy, macro_sell = evaluate_macro_slope(macro_current, macro_prev)
    forex_scores = evaluate_forex(twd_current, twd_prev)
    llm_score = extract_llm_score(llm_text)
    
    if is_owned:
        # --- 進入【賣出軌道 (SELL Track)】 ---
        is_profitable = current_price > buy_price
        stock_sell = evaluate_held_stock_sell(momentum_index, is_profitable)
        llm_sell = 100 - llm_score # LLM 分數反轉 (看好 = 不想賣)
        
        # 動態乘數：個股超買(連漲) * 大盤賣出信心
        if momentum_index > 0:
            stock_sell = stock_sell * (macro_sell / 100.0) 
            
        total_score = (
            (macro_sell * WEIGHT_MACRO) +
            (stock_sell * WEIGHT_STOCK) +
            (llm_sell * WEIGHT_LLM) +
            (forex_scores["sell"] * WEIGHT_TWD)
        )
        action = "賣出 (SELL)" if total_score >= THRESHOLD_SELL else "觀望 (HOLD)"
        return {"stock_id": stock_id, "action": action, "score": round(total_score, 2), "track": "SELL"}
        
    else:
        # --- 進入【買進軌道 (BUY Track)】 ---
        stock_buy = evaluate_unowned_stock_buy(momentum_index)
        
        total_score = (
            (macro_buy * WEIGHT_MACRO) +
            (stock_buy * WEIGHT_STOCK) +
            (llm_score * WEIGHT_LLM) +
            (forex_scores["buy"] * WEIGHT_TWD)
        )
        action = "買進 (BUY)" if total_score >= THRESHOLD_BUY else "觀望 (HOLD)"
        return {"stock_id": stock_id, "action": action, "score": round(total_score, 2), "track": "BUY"}

# ==========================================
# 部位管理與儲存系統 (Portfolio Manager)
# ==========================================
class PortfolioManager:
    def __init__(self, filepath="my_portfolio.json"):
        """初始化部位管理器，包含比賽規定的 10 億初始資金"""
        self.filepath = filepath
        self.cash = 1000000000 
        self.holdings = {}     
        self.load_data()

    def load_data(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.cash = data.get("cash", 1000000000)
                self.holdings = data.get("holdings", {})

    def save_data(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump({"cash": self.cash, "holdings": self.holdings}, f, indent=4, ensure_ascii=False)

    def get_nav(self, current_prices):
        """計算總投資組合淨值 (NAV)"""
        total_stock_value = 0
        for stock_id, data in self.holdings.items():
            price = current_prices.get(stock_id, data["buy_price"])
            total_stock_value += price * data["shares"] * 1000
        return self.cash + total_stock_value

    def calculate_order_size(self, stock_id, action, score, price, current_prices):
        """根據信心分數與比賽規則，動態計算該買/賣幾張"""
        nav = self.get_nav(current_prices)
        
        if "BUY" in action:
            # 依據分數決定資金比例 (滿分約佔淨值 4.5%)
            target_weight = 0.045 * (score / 100) 
            
            # 競賽規則：台積電上限 25%，其餘上限 10%
            max_weight_limit = 0.25 if stock_id == "2330" else 0.10
            target_weight = min(target_weight, max_weight_limit)
            
            current_held_value = self.holdings.get(stock_id, {}).get("shares", 0) * price * 1000
            allowable_buy_money = (nav * target_weight) - current_held_value
            
            # 競賽規則：保留合理現金水位
            buy_money = max(0, min(allowable_buy_money, self.cash * 0.90))
            return int(buy_money // (price * 1000))
            
        elif "SELL" in action:
            if stock_id not in self.holdings: return 0
            current_shares = self.holdings[stock_id]["shares"]
            
            if score >= 80:
                return current_shares # 極度危險或停損：清倉 100%
            else:
                return max(1, current_shares // 2) # 一般停利：減碼 50%
        return 0

    def execute_trade(self, stock_id, action, price, shares):
        """模擬執行交易，計算手續費與稅，並更新庫存"""
        if shares <= 0: return None
        
        cost_base = price * shares * 1000 
        trade_record = None
        
        if "BUY" in action:
            total_cost = cost_base * (1 + 0.001425) 
            if self.cash >= total_cost:
                self.cash -= total_cost
                if stock_id in self.holdings:
                    old_s = self.holdings[stock_id]["shares"]
                    old_p = self.holdings[stock_id]["buy_price"]
                    new_price = ((old_p * old_s) + (price * shares)) / (old_s + shares)
                    self.holdings[stock_id]["shares"] += shares
                    self.holdings[stock_id]["buy_price"] = round(new_price, 2)
                else:
                    self.holdings[stock_id] = {"buy_price": price, "shares": shares}
                trade_record = {"stock_id": stock_id, "type": "BUY", "price": price, "shares": shares}
                
        elif "SELL" in action:
            if stock_id in self.holdings:
                sell_shares = min(shares, self.holdings[stock_id]["shares"])
                net_income = (price * sell_shares * 1000) * (1 - 0.001425 - 0.003) 
                self.cash += net_income
                self.holdings[stock_id]["shares"] -= sell_shares
                trade_record = {"stock_id": stock_id, "type": "SELL", "price": price, "shares": sell_shares}
                if self.holdings[stock_id]["shares"] <= 0:
                    del self.holdings[stock_id] 
                    
        self.save_data()
        return trade_record

# ==========================================
# 實戰競賽用：每日排程執行區塊 (Daily Execution Job)
# ==========================================
if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行 Agent 每日決策程序...")
    
    # 初始化投資組合管理器
    portfolio = PortfolioManager()
    
    # ---------------------------------------------------------
    # TODO 1: 透過爬蟲或 API 獲取總經數據與 150 檔台股個股資訊
    # ---------------------------------------------------------
    # 例如：
    # macro_today, macro_yesterday = fetch_nasdaq_data()
    # twd_today, twd_yesterday = fetch_forex_data()
    # allowed_150_stocks = fetch_competition_stock_list()
    # market_prices = fetch_current_prices(allowed_150_stocks)
    
    # 模擬佔位變數 (請替換為真實資料)
    macro_today, macro_yesterday = 1.0, 0.5 
    twd_today, twd_yesterday = 32.1, 32.2 
    allowed_150_stocks = ["2330", "2454", "3231"] # 須包含 150 檔
    market_prices = {"2330": 1050, "2454": 1200, "3231": 150} 
    
    # ---------------------------------------------------------
    # TODO 2: 生成所有 150 檔股票的決策與信心分數
    # ---------------------------------------------------------
    daily_decisions = []
    
    for stock_id in allowed_150_stocks:
        # TODO: 計算個股動能指數 (momentum_index)
        momentum = 1 
        
        # TODO: 呼叫 Google Cloud Vertex AI (Gemini) 獲取該股票的新聞分析分數
        llm_analysis_text = "看好未來發展，信心分數：85" 
        
        is_owned = stock_id in portfolio.holdings
        buy_price = portfolio.holdings.get(stock_id, {}).get("buy_price", 0)
        current_price = market_prices.get(stock_id, 0)
        
        decision = generate_trading_decision(
            stock_id=stock_id, 
            is_owned=is_owned,
            macro_current=macro_today, 
            macro_prev=macro_yesterday, 
            twd_current=twd_today, 
            twd_prev=twd_yesterday, 
            momentum_index=momentum, 
            llm_text=llm_analysis_text,
            current_price=current_price, 
            buy_price=buy_price
        )
        daily_decisions.append(decision)
    
    # ---------------------------------------------------------
    # TODO 3: 競賽核心規則檢查與過濾 (非常重要)
    # ---------------------------------------------------------
    # 規則 1: 每日投資組合需介於 20-30 檔個股間。
    
    daily_trade_report = []
    
    # 1. 優先執行所有「賣出 (SELL)」決策，釋放資金與檔數空間
    for d in daily_decisions:
        if "SELL" in d["action"]:
            stock_id = d["stock_id"]
            price = market_prices.get(stock_id, 0)
            shares = portfolio.calculate_order_size(stock_id, "SELL", d["score"], price, market_prices)
            
            record = portfolio.execute_trade(stock_id, "SELL", price, shares)
            if record:
                daily_trade_report.append(record)
                
    # 2. 計算剩餘庫存檔數
    current_holding_count = len(portfolio.holdings)
    
    # 3. 整理「買進 (BUY)」候選名單，排除已經在手上的，並依分數由高至低排序
    buy_candidates = [d for d in daily_decisions if "BUY" in d["action"] and d["stock_id"] not in portfolio.holdings]
    buy_candidates = sorted(buy_candidates, key=lambda x: x["score"], reverse=True)
    
    # 4. 精準控制買進數量的防呆機制
    max_can_buy = 30 - current_holding_count       # 最多還能買幾檔 (不能破 30)
    min_must_buy = max(0, 20 - current_holding_count) # 至少還要買幾檔 (不能低於 20)
    
    bought_count = 0
    for target in buy_candidates:
        if bought_count >= max_can_buy:
            break  # 已經達到 30 檔滿水位，強迫停止買進
            
        # 買進決策：分數大於等於買進門檻，或者「為了保命湊滿 20 檔」分數不夠也要硬買
        if target["score"] >= THRESHOLD_BUY or bought_count < min_must_buy:
            stock_id = target["stock_id"]
            price = market_prices.get(stock_id, 0)
            
            shares = portfolio.calculate_order_size(stock_id, "BUY", target["score"], price, market_prices)
            
            # 確保資金足夠買進至少1張才算成功進場
            if shares > 0:
                record = portfolio.execute_trade(stock_id, "BUY", price, shares)
                if record:
                    daily_trade_report.append(record)
                    bought_count += 1

    # 每日最終安全斷言 (除錯用，實戰若印出警告代表需要微調)
    final_count = len(portfolio.holdings)
    if final_count < 20 or final_count > 30:
        print(f"⚠️ 嚴重警告：今日投資組合檔數為 {final_count}，違反比賽 20~30 檔規定！")
    else:
        print(f"✅ 檔數檢核通過：今日持有 {final_count} 檔個股。")
                
    # ---------------------------------------------------------
    # TODO 4: 產出「當日 Agent 決策報告及交易書」
    # ---------------------------------------------------------
    report_filename = f"trading_report_{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_filename, 'w', encoding='utf-8') as f:
        json.dump(daily_trade_report, f, indent=4, ensure_ascii=False)
        
    print(f"✅ 決策完成！當前總淨值 (NAV): {portfolio.get_nav(market_prices):,.0f} 元")
    print(f"✅ 現金剩餘: {portfolio.cash:,.0f} 元")
    print(f"✅ 持股檔數: {len(portfolio.holdings)} 檔")
    print(f"📄 已產出交易書: {report_filename}")