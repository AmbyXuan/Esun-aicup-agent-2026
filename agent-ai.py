import json
import os
import re
from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    yf = None
    print("⚠️ 提醒：尚未安裝 yfinance，股價與新聞抓取將使用備用假資料。請執行 pip install yfinance")


# ==========================================
# 模組 1：投資組合與記憶管理員 (大腦記憶區)
# ==========================================
class PortfolioManager:
    def __init__(self, filename="my_portfolio.json"):
        self.filename = filename
        self.cash = 1000000000  # 初始本金 10 億台幣
        self.positions = {}     # 庫存紀錄
        self.load_portfolio()

    def load_portfolio(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.cash = data.get("cash", self.cash)
                self.positions = data.get("positions", {})

    def save_portfolio(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump({"cash": self.cash, "positions": self.positions}, f, indent=4, ensure_ascii=False)

    def get_nav(self, current_prices):
        stock_value = 0
        for stock_id, pos in self.positions.items():
            price = current_prices.get(stock_id, pos['buy_price'])
            stock_value += pos['shares'] * price * 1000
        return self.cash + stock_value

    def calculate_order_size(self, confidence_score):
        max_weight_limit = 0.10  
        if confidence_score >= 90: return max_weight_limit * 0.4
        elif confidence_score >= 70: return max_weight_limit * 0.3
        else: return 0

    def execute_trade(self, stock_id, action, current_price, size_ratio=None, shares_to_sell=None):
        fee_rate = 0.001425  
        tax_rate = 0.003     
        today_str = datetime.now().strftime('%Y-%m-%d')

        if action == "BUY" and size_ratio:
            target_amount = self.cash * size_ratio
            shares_to_buy = int(target_amount / (current_price * 1000))
            
            if shares_to_buy > 0:
                cost = shares_to_buy * current_price * 1000
                fee = cost * fee_rate
                total_cost = cost + fee
                
                if self.cash >= total_cost:
                    self.cash -= total_cost
                    if stock_id in self.positions:
                        old_shares = self.positions[stock_id]['shares']
                        old_price = self.positions[stock_id]['buy_price']
                        old_date = self.positions[stock_id].get('buy_date', today_str)
                        new_total_shares = old_shares + shares_to_buy
                        new_avg_price = ((old_shares * old_price) + (shares_to_buy * current_price)) / new_total_shares
                        self.positions[stock_id]['shares'] = new_total_shares
                        self.positions[stock_id]['buy_price'] = new_avg_price
                        self.positions[stock_id]['buy_date'] = old_date
                    else:
                        self.positions[stock_id] = {
                            'shares': shares_to_buy, 
                            'buy_price': current_price,
                            'buy_date': today_str 
                        }
        
        elif action == "SELL" and shares_to_sell:
            if stock_id in self.positions and self.positions[stock_id]['shares'] >= shares_to_sell:
                revenue = shares_to_sell * current_price * 1000
                fee = revenue * fee_rate
                tax = revenue * tax_rate
                net_revenue = revenue - fee - tax
                
                self.cash += net_revenue
                self.positions[stock_id]['shares'] -= shares_to_sell
                
                if self.positions[stock_id]['shares'] <= 0:
                    del self.positions[stock_id]

        self.save_portfolio()


# ==========================================
# 模組 2：資訊獲取與 API 串接 (眼睛與耳朵)
# ==========================================
def get_real_macro_data():
    if not yf: return 0.1, 1.5
    try:
        djia = yf.Ticker("^DJI")
        hist = djia.history(period="5d")
        if len(hist) >= 3:
            pct_changes = hist['Close'].pct_change().dropna() * 100
            today_change = round(pct_changes.iloc[-1], 2)
            yesterday_change = round(pct_changes.iloc[-2], 2)
            return today_change, yesterday_change
    except:
        pass
    return 0.1, 1.5

def get_real_stock_data(stock_id, start_date=None):
    if not yf: return 100, 3 
    try:
        ticker = yf.Ticker(stock_id)
        if start_date:
            hist = ticker.history(start=start_date)
            if len(hist) == 0:
                hist = ticker.history(period="5d")
        else:
            hist = ticker.history(period="5d")
            
        current_price = round(hist['Close'].iloc[-1], 2)
        
        momentum = 0
        if len(hist) > 1:
            diffs = hist['Close'].diff().dropna()
            for diff in diffs:
                if diff > 0: momentum += 1
                elif diff < 0: momentum -= 1
                
        return current_price, momentum
    except:
        return 100, 3

def fetch_real_news(stock_id):
    if not yf: return "無法抓取新聞"
    try:
        ticker = yf.Ticker(stock_id) 
        news_data = ticker.news
        if not news_data: return "今日無相關重大新聞。"
        return " | ".join([item.get('title', '') for item in news_data[:3]])
    except:
        return "新聞抓取失敗"

def get_structured_llm_analysis(news_content):
    prompt = f"""
    請閱讀以下新聞，判斷該股票未來趨勢。
    新聞：{news_content}
    請嚴格以下列 JSON 格式輸出，不要包含任何其他文字：
    {{"score": 85, "explanation": "看好的原因"}}
    """
    
    # [缺口一：真實 LLM API 串接] 
    # (未來請刪除下方 if-else 測試區塊，換成真實的 response = llm.generate(prompt) 等程式碼)
    if "無相關" in news_content or "失敗" in news_content:
        raw_output = '{"score": 50, "explanation": "缺乏新聞資訊，給予中立評價。"}'
    else:
        raw_output = '{"score": 75, "explanation": "近期有相關市場動態，可能帶動波段行情。"}'
        
    try:
        clean_json = raw_output.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        return data
    except:
        return {"score": 50, "explanation": "JSON 解析失敗，預設為 50 分。"}


# ==========================================
# 模組 3：核心評分演算法 (大腦決策邏輯)
# ==========================================
def evaluate_macro_slope(today_change, yesterday_change):
    delta = today_change - yesterday_change
    if today_change > 0:
        if delta < 0: return {"buy": max(0, 40 - abs(delta)*10), "sell": min(100, 60 + abs(delta)*30)}
        else: return {"buy": min(100, 70 + delta*20), "sell": max(0, 30 - delta*10)}
    else:
        if delta > 0: return {"buy": min(100, 60 + delta*30), "sell": max(0, 40 - delta*10)}
        else: return {"buy": max(0, 20 - abs(delta)*10), "sell": min(100, 60 + abs(delta)*20)}

def evaluate_held_stock_sell(momentum_index, is_profitable):
    if momentum_index < 0:
        base_sell_score = 60 + (abs(momentum_index) * 10)
        if not is_profitable: base_sell_score += 20
    else:
        base_sell_score = 50 - (momentum_index * 10)
        if is_profitable: base_sell_score += 15
    return max(0, min(100, base_sell_score))

def generate_trading_decision(macro_today, macro_yesterday, fx_today, fx_yesterday, stock_id, momentum_index, is_owned, is_profitable, llm_data):
    macro_scores = evaluate_macro_slope(macro_today, macro_yesterday)
    fx_trend = fx_today - fx_yesterday
    fx_buy_score = 80 if fx_trend < 0 else 30
    fx_sell_score = 80 if fx_trend > 0 else 30
    
    llm_score = llm_data.get("score", 50)
    llm_sell_score = 100 - llm_score
    
    if not is_owned:
        stock_buy_score = 50 + (momentum_index * 10)
        total_buy_score = (macro_scores["buy"] * 0.3) + (stock_buy_score * 0.3) + (llm_score * 0.2) + (fx_buy_score * 0.2)
        return {"action": "BUY" if total_buy_score >= 70 else "HOLD", "score": total_buy_score}
    else:
        stock_sell_score = evaluate_held_stock_sell(momentum_index, is_profitable)
        macro_multiplier = macro_scores["sell"] / 100.0
        if momentum_index > 0: stock_sell_score = stock_sell_score * macro_multiplier
        total_sell_score = (macro_scores["sell"] * 0.3) + (stock_sell_score * 0.3) + (llm_sell_score * 0.2) + (fx_sell_score * 0.2)
        
        if total_sell_score >= 80: return {"action": "SELL_ALL", "score": total_sell_score}
        elif total_sell_score >= 65: return {"action": "SELL_HALF", "score": total_sell_score}
        else: return {"action": "HOLD", "score": total_sell_score}


# ==========================================
# 模組 4：每日執行腳本 (當日報紙與執行區塊)
# ==========================================
if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行 Agent 每日決策程序...")
    
    pm = PortfolioManager()
    
    MACRO_TODAY, MACRO_YESTERDAY = get_real_macro_data()
    
    # [缺口二：真實匯率資料]
    FX_TODAY = 32.5
    FX_YESTERDAY = 32.0
    
    # [缺口三：競賽 150 檔股票池]
    allowed_150_stocks = [
        {"id": "2330.TW"},
        {"id": "2454.TW"},
        {"id": "3231.TW"}
    ]
    
    today_buy_scores = {}
    today_transactions = []
    current_prices = {} 
    
    # 階段 A：先評估手上現有持股是否該賣
    stocks_to_evaluate_sell = list(pm.positions.keys())
    for stock_id in stocks_to_evaluate_sell:
        buy_date = pm.positions[stock_id].get('buy_date')
        current_price, momentum = get_real_stock_data(stock_id, start_date=buy_date)
        current_prices[stock_id] = current_price
        
        news_content = fetch_real_news(stock_id)
        llm_analysis_data = get_structured_llm_analysis(news_content)
        
        mock_buy_price = pm.positions[stock_id]['buy_price']
        is_profitable = current_price > mock_buy_price
        
        decision = generate_trading_decision(
            MACRO_TODAY, MACRO_YESTERDAY, FX_TODAY, FX_YESTERDAY,
            stock_id, momentum_index=momentum, is_owned=True, is_profitable=is_profitable, llm_data=llm_analysis_data
        )
        
        if decision["action"] in ["SELL_ALL", "SELL_HALF"]:
            shares_held = pm.positions[stock_id]['shares']
            sell_amount = shares_held if decision["action"] == "SELL_ALL" else int(shares_held / 2)
            if sell_amount > 0:
                pm.execute_trade(stock_id, "SELL", current_price, shares_to_sell=sell_amount)
                today_transactions.append({"stock_id": stock_id, "action": "SELL", "shares": sell_amount, "price": current_price})

    # 階段 B：評估新標的買進潛力
    for stock in allowed_150_stocks:
        if stock["id"] not in pm.positions:
            current_price, momentum = get_real_stock_data(stock["id"])
            current_prices[stock["id"]] = current_price
            
            news_content = fetch_real_news(stock["id"])
            llm_analysis_data = get_structured_llm_analysis(news_content)
            
            decision = generate_trading_decision(
                MACRO_TODAY, MACRO_YESTERDAY, FX_TODAY, FX_YESTERDAY,
                stock["id"], momentum_index=momentum, is_owned=False, is_profitable=False, llm_data=llm_analysis_data
            )
            
            if decision["action"] == "BUY":
                today_buy_scores[stock["id"]] = decision["score"]

    # 嚴格執行買進與 20~30 檔防呆機制
    current_holding_count = len(pm.positions)
    buy_candidates = [{"id": s_id, "score": score} for s_id, score in today_buy_scores.items() if s_id not in pm.positions]
    buy_candidates = sorted(buy_candidates, key=lambda x: x["score"], reverse=True)
    
    max_can_buy = 30 - current_holding_count
    min_must_buy = max(0, 20 - current_holding_count)
    
    bought_count = 0
    for target in buy_candidates:
        if bought_count >= max_can_buy:
            break
            
        if target["score"] >= 70 or bought_count < min_must_buy:
            size_ratio = pm.calculate_order_size(target["score"])
            target_current_price = current_prices[target["id"]]
            
            pm.execute_trade(target["id"], "BUY", target_current_price, size_ratio=size_ratio)
            
            target_amount = pm.cash * size_ratio
            shares_bought = int(target_amount / (target_current_price * 1000))
            if shares_bought > 0:
                today_transactions.append({"stock_id": target["id"], "action": "BUY", "shares": shares_bought, "price": target_current_price})
                bought_count += 1
            
    # 每日結算與狀態檢核
    final_count = len(pm.positions)
    if final_count < 20 or final_count > 30:
        print(f"⚠️ 嚴重警告：今日投資組合檔數為 {final_count}，違反比賽 20~30 檔規定！")
    else:
        print(f"✅ 檔數檢核通過：今日持有 {final_count} 檔個股。")
        
    print(f"✅ 決策完成！當前總淨值 (NAV): {pm.get_nav(current_prices):,.0f} 元")
    print(f"✅ 現金剩餘: {pm.cash:,.0f} 元")
    
    report_filename = f"trading_report_{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_filename, 'w', encoding='utf-8') as f:
        json.dump(today_transactions, f, indent=4, ensure_ascii=False)
    
    print(f"📄 已產出交易書: {report_filename}")