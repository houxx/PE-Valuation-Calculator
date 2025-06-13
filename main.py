import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import json
import io
import base64
import warnings
from cache_manager import CacheManager
warnings.filterwarnings('ignore')

# 页面配置
st.set_page_config(
    page_title="PE估值计算器",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义CSS样式
st.markdown("""
<style>
.main-header {
    font-size: 2.5rem;
    font-weight: bold;
    color: #1f77b4;
    text-align: center;
    margin-bottom: 2rem;
}
.metric-card {
    background-color: #f0f2f6;
    padding: 1rem;
    border-radius: 0.5rem;
    border-left: 4px solid #1f77b4;
}
.highlight {
    background-color: #e8f4fd;
    padding: 1rem;
    border-radius: 0.5rem;
    border: 1px solid #1f77b4;
    margin: 1rem 0;
}
</style>
""", unsafe_allow_html=True)

class PECalculator:
    def __init__(self):
        self.ticker = None
        self.stock_data = None
        self.eps_ttm = None
        self.industry_pe = None
        self.cache_manager = CacheManager()
        
    def get_stock_data(self, ticker, period="1y", force_refresh=False):
        """获取股票历史数据"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'stock_price', period=period)
            if cached_data:
                data, info = cached_data[0]
                update_time = self.cache_manager.get_data_update_time(ticker, 'stock_price', period=period)
                st.write(f"✅ 使用缓存的股价数据 (更新时间: {update_time})")
                st.write("股价数据已从缓存加载，无需重新获取")
                return data, info
        
        try:
            st.write("🔄 正在获取最新股价数据...")
            st.write("正在从Yahoo Finance获取股价数据...")
            stock = yf.Ticker(ticker)
            data = stock.history(period=period)
            info = stock.info
            
            # 保存到缓存
            self.cache_manager.save_cache(ticker, 'stock_price', (data, info), period=period)
            st.write("✅ 股价数据获取成功并已缓存")
            st.write("股价数据已成功获取并保存到缓存")
            
            return data, info
        except Exception as e:
            st.error(f"获取股票数据失败: {e}")
            return None, None
    
    def get_eps_ttm(self, ticker, force_refresh=False):
        """获取TTM EPS数据"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'eps_data')
            if cached_data:
                eps_ttm = cached_data[0]
                update_time = self.cache_manager.get_data_update_time(ticker, 'eps_data')
                st.write(f"✅ 使用缓存的EPS数据 (更新时间: {update_time})")
                st.write("EPS数据已从缓存加载，无需重新获取")
                return eps_ttm
        
        try:
            st.write("🔄 正在获取最新EPS数据...")
            st.write("正在从Yahoo Finance获取EPS数据...")
            stock = yf.Ticker(ticker)
            info = stock.info
            eps_ttm = info.get('trailingEps', None)
            if eps_ttm is None or eps_ttm <= 0:
                # 尝试从财务数据获取
                financials = stock.financials
                if not financials.empty:
                    net_income = financials.loc['Net Income'].iloc[0] if 'Net Income' in financials.index else None
                    shares = info.get('sharesOutstanding', None)
                    if net_income and shares:
                        eps_ttm = net_income / shares
            
            # 保存到缓存
            if eps_ttm and eps_ttm > 0:
                self.cache_manager.save_cache(ticker, 'eps_data', eps_ttm)
                st.write("✅ 股价数据获取成功并已缓存")
                st.write("股价数据已成功获取并保存到缓存")
            
            return eps_ttm
        except Exception as e:
            st.warning(f"获取EPS数据失败: {e}")
            return None
    
    def calculate_pe_range(self, price_data, eps):
        """计算PE区间"""
        if eps is None or eps <= 0:
            return None
        
        pe_values = price_data['Close'] / eps
        pe_values = pe_values.dropna()
        
        if pe_values.empty:
            return None
        
        pe_mean = pe_values.mean()
        pe_std = pe_values.std()
        pe_median = pe_values.median()
        pe_min = pe_values.min()
        pe_max = pe_values.max()
        
        # 使用均值±1标准差作为区间
        pe_lower = max(0, pe_mean - pe_std)
        pe_upper = pe_mean + pe_std
        
        return {
            'pe_mean': round(pe_mean, 2),
            'pe_median': round(pe_median, 2),
            'pe_std': round(pe_std, 2),
            'pe_lower': round(pe_lower, 2),
            'pe_upper': round(pe_upper, 2),
            'pe_min': round(pe_min, 2),
            'pe_max': round(pe_max, 2),
            'pe_values': pe_values,
            'data_points': len(pe_values)
        }
    
    def get_eps_from_seeking_alpha(self, ticker):
        """从Seeking Alpha获取EPS估算数据 - 已移除自动抓取功能"""
        # 移除了Seeking Alpha自动抓取功能，改为手动输入提示
        st.info("💡 提示：由于网站反爬虫限制，请手动输入EPS预测数据")
        return {}
    
    def get_industry_pe_data(self, ticker, force_refresh=False, api_key=None):
        """获取行业平均PE数据"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'industry_data')
            if cached_data:
                industry_data = cached_data[0]
                update_time = self.cache_manager.get_data_update_time(ticker, 'industry_data')
                st.write(f"✅ 使用缓存的行业数据 (更新时间: {update_time})")
                st.write("行业数据已从缓存加载，无需重新获取")
                return industry_data
        
        industry_data = {
            'industry_name': None,
            'industry_pe': None,
            'sector_pe': None,
            'market_pe': None
        }
        
        try:
            st.write("🔄 正在获取最新行业数据...")
            st.write("正在从Yahoo Finance获取行业信息...")
            # 方法1: 从yfinance获取行业信息
            stock = yf.Ticker(ticker)
            info = stock.info
            
            industry = info.get('industry', 'N/A')
            sector = info.get('sector', 'N/A')
            
            industry_data['industry_name'] = industry
            industry_data['sector_name'] = sector
            
            st.write(f"🏭 检测到行业: {industry} | 板块: {sector}")
            st.write(f"行业分类: {industry}")
            st.write(f"板块分类: {sector}")
            
            # 方法2: 尝试从Financial Modeling Prep API获取行业和板块PE数据
            fmp_api_key = api_key or st.session_state.get('fmp_api_key', None)
            industry_pe = None
            sector_pe = None
            
            if fmp_api_key:
                try:
                    st.write("🔄 正在从Financial Modeling Prep获取实时行业PE数据...")
                    st.write("正在请求行业PE数据...")
                    
                    # 获取行业PE数据
                    industry_pe_url = f"https://financialmodelingprep.com/api/v4/industry_price_earning_ratio?apikey={fmp_api_key}"
                    industry_response = requests.get(industry_pe_url, timeout=10)
                    
                    if industry_response.status_code == 200:
                        industry_data_list = industry_response.json()
                        if industry_data_list and isinstance(industry_data_list, list):
                            # 查找匹配的行业
                            for item in industry_data_list:
                                if item.get('industry', '').lower() == industry.lower():
                                    industry_pe = item.get('pe', None)
                                    break
                            
                            if industry_pe is not None:
                                st.write(f"✅ 获取到实时行业PE数据")
                                st.write(f"行业: {industry}")
                                st.write(f"PE比率: {industry_pe}")
                                st.write("数据来源: Financial Modeling Prep API")
                            else:
                                st.write(f"⚠️ 未找到匹配的行业PE数据")
                                st.write(f"行业: {industry}")
                                st.write("未在API返回结果中找到匹配的行业数据")
                    else:
                        st.write(f"⚠️ 行业PE数据API请求失败")
                        st.write(f"状态码: {industry_response.status_code}")
                        st.write("将使用预设数据作为备用方案")
                    
                    # 获取板块PE数据
                    st.write("🔄 正在从Financial Modeling Prep获取实时板块PE数据...")
                    st.write("正在请求板块PE数据...")
                    
                    sector_pe_url = f"https://financialmodelingprep.com/api/v4/sector_price_earning_ratio?apikey={fmp_api_key}"
                    sector_response = requests.get(sector_pe_url, timeout=10)
                    
                    if sector_response.status_code == 200:
                        sector_data_list = sector_response.json()
                        if sector_data_list and isinstance(sector_data_list, list):
                            # 查找匹配的板块
                            for item in sector_data_list:
                                if item.get('sector', '').lower() == sector.lower():
                                    sector_pe = item.get('pe', None)
                                    break
                            
                            if sector_pe is not None:
                                st.write(f"✅ 获取到实时板块PE数据")
                                st.write(f"板块: {sector}")
                                st.write(f"PE比率: {sector_pe}")
                                st.write("数据来源: Financial Modeling Prep API")
                            else:
                                st.write(f"⚠️ 未找到匹配的板块PE数据")
                                st.write(f"板块: {sector}")
                                st.write("未在API返回结果中找到匹配的板块数据")
                    else:
                        st.write(f"⚠️ 板块PE数据API请求失败")
                        st.write(f"状态码: {sector_response.status_code}")
                        st.write("将使用预设数据作为备用方案")
                        
                except Exception as e:
                    st.write(f"⚠️ Financial Modeling Prep API请求异常")
                    st.write(f"错误信息: {str(e)}")
                    st.write("将使用预设数据作为备用方案")
            else:
                st.write("ℹ️ 未使用Financial Modeling Prep API")
                st.write("原因: 未提供API密钥")
                st.write("将使用预设数据作为备用方案")
            
            # 如果API获取成功，使用API数据；否则使用None表示无数据
            if industry_pe is not None:
                industry_data['industry_pe'] = industry_pe
                st.write(f"✅ 使用实时行业PE数据: {industry_pe}")
                st.write(f"行业: {industry}")
                st.write(f"PE比率: {industry_pe}")
                st.write("数据来源: Financial Modeling Prep API")
            else:
                industry_data['industry_pe'] = None
                st.write(f"⚠️ 无法获取行业PE数据")
                st.write(f"行业: {industry}")
                st.write("未能获取PE比率数据")
                st.write(f"原因: 未找到{industry}行业的PE数据或未提供API密钥")
            
            # 设置板块PE
            if sector_pe is not None:
                industry_data['sector_pe'] = sector_pe
                st.write(f"✅ 使用实时板块PE数据: {sector_pe}")
                st.write(f"板块: {sector}")
                st.write(f"PE比率: {sector_pe}")
                st.write("数据来源: Financial Modeling Prep API")
            else:
                industry_data['sector_pe'] = None
                st.write(f"⚠️ 无法获取板块PE数据")
                st.write(f"板块: {sector}")
                st.write("未能获取PE比率数据")
                st.write(f"原因: 未找到{sector}板块的PE数据或未提供API密钥")
            
            # 设置市场平均PE - 不使用预设值
            industry_data['market_pe'] = None
            
            # 保存到缓存
            self.cache_manager.save_cache(ticker, 'industry_data', industry_data)
            st.write("✅ 行业数据获取成功并已缓存")
            st.write("行业数据已成功获取并保存到缓存")
            
        except Exception as e:
            st.error(f"获取行业数据失败: {e}")
            # 使用默认值
            industry_data = {
                'industry_name': 'Unknown',
                'sector_name': 'Unknown',
                'industry_pe': None,
                'sector_pe': None,
                'market_pe': None
            }
        
        return industry_data
    
    def get_forward_eps_estimates(self, ticker, force_refresh=False):
        """获取前瞻EPS预测 - 仅使用真实查询数据，不进行估算"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'forward_eps')
            if cached_data:
                estimates = cached_data[0]
                update_time = self.cache_manager.get_data_update_time(ticker, 'forward_eps')
                st.write(f"✅ 使用缓存的前瞻EPS数据 (更新时间: {update_time})")
                return estimates
        
        st.write("🔄 正在获取最新前瞻EPS数据...")
        current_year = datetime.now().year
        estimates = {
            str(current_year + 1): None,
            str(current_year + 2): None,
            str(current_year + 3): None
        }
        
        # 方法1: 尝试从yfinance获取分析师预测（仅使用真实数据）
        st.write("🔄 尝试从yfinance获取EPS预测...")
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # 仅获取真实的前瞻EPS数据，不进行估算
            forward_eps = info.get('forwardEps', None)
            
            if forward_eps and forward_eps > 0:
                estimates[str(current_year + 1)] = float(forward_eps)
                st.write(f"✅ 从yfinance获取到前瞻EPS: ${forward_eps}")
            else:
                st.write("⚠️ yfinance未提供有效的前瞻EPS数据")
                
        except Exception as e:
            st.write(f"⚠️ yfinance EPS数据获取失败: {e}")
        
        # 方法2: 尝试从Financial Modeling Prep获取数据（仅使用真实数据）
        if not any(estimates.values()):
            st.write("🔄 尝试从Financial Modeling Prep获取EPS预测...")
            try:
                # 注意：demo API key有限制，建议用户申请自己的API key
                fmp_url = f"https://financialmodelingprep.com/api/v3/analyst-estimates/{ticker}?limit=10&apikey=demo"
                response = requests.get(fmp_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        eps_found = False
                        for item in data:
                            year = item.get('date', '')[:4]  # 获取年份
                            eps_estimate = item.get('estimatedEpsAvg', None)
                            
                            if year in estimates and eps_estimate and eps_estimate > 0:
                                estimates[year] = float(eps_estimate)
                                eps_found = True
                                
                        if eps_found:
                            st.write("✅ 从Financial Modeling Prep获取EPS预测数据")
                        else:
                            st.write("⚠️ Financial Modeling Prep返回数据但无有效EPS")
                    else:
                        st.write("⚠️ Financial Modeling Prep未返回有效数据")
                else:
                    st.write(f"⚠️ Financial Modeling Prep API请求失败，状态码: {response.status_code}")
            except Exception as e:
                st.write(f"⚠️ Financial Modeling Prep数据获取失败: {e}")
        
        # 显示获取结果
        if any(estimates.values()):
            st.write("✅ 成功获取部分前瞻EPS数据")
            for year, eps in estimates.items():
                if eps:
                    st.write(f"- {year}年: ${eps}")
        else:
            st.write("⚠️ 未能从API获取到前瞻EPS数据")
        
        # 手动输入说明
        st.markdown("### 📝 手动输入EPS预测数据")
        st.markdown("💡 **重要提示：** 程序不会自动估算EPS数据，请根据以下来源手动填写准确的分析师预测数据")
        
        # 添加数据获取说明
        st.markdown("""
        **推荐数据来源：**
        
        1. **Seeking Alpha** (推荐)
           - 搜索股票代码 → Earnings → Earnings Estimates
           - 查看"EPS Estimate"表格中的未来年份预测
        
        2. **Yahoo Finance**
           - 搜索股票 → Analysis → Earnings Estimate
           - 查看"Earnings Estimate"部分
        
        3. **Bloomberg Terminal** (专业用户)
           - 输入股票代码 → EE (Earnings Estimates)
        
        4. **公司财报和投资者关系页面**
           - 查看公司官方指引和分析师报告
        
        **注意：** 请确保使用最新的分析师一致预期数据，避免使用过时信息
        """)
        
        # 保存到缓存（即使部分数据为空也保存，避免重复查询）
        self.cache_manager.save_cache(ticker, 'forward_eps', estimates)
        st.write("✅ 查询结果已缓存")
            
        return estimates
    
    def calculate_valuation(self, forward_eps, pe_range):
        """计算前瞻估值"""
        if not pe_range:
            return None
        
        results = []
        pe_lower = pe_range['pe_lower']
        pe_upper = pe_range['pe_upper']
        pe_median = pe_range['pe_median']
        
        for year, eps in forward_eps.items():
            if eps and eps > 0:  # 只处理有效的EPS数据
                valuation_lower = eps * pe_lower
                valuation_upper = eps * pe_upper
                valuation_median = eps * pe_median
                
                results.append({
                    'year': year,
                    'eps': f"${eps:.2f}",
                    'eps_raw': eps,
                    'pe_range': f"{pe_lower:.2f}–{pe_upper:.2f}",
                    'valuation_lower': valuation_lower,
                    'valuation_upper': valuation_upper,
                    'valuation_median': valuation_median,
                    'valuation_range': f"${valuation_lower:.2f} – ${valuation_upper:.2f}（中位：${valuation_median:.2f}）",
                    'source': 'Yahoo Finance 分析师共识'
                })
        
        return results

def create_valuation_chart(valuation_results):
    """创建估值图表"""
    if not valuation_results:
        return None
    
    years = [result['year'] for result in valuation_results]
    lower_values = [result['valuation_lower'] for result in valuation_results]
    upper_values = [result['valuation_upper'] for result in valuation_results]
    median_values = [result['valuation_median'] for result in valuation_results]
    
    fig = go.Figure()
    
    # 添加估值区间柱状图
    fig.add_trace(go.Bar(
        x=years,
        y=upper_values,
        name='估值上限',
        marker_color='lightcoral',
        opacity=0.7
    ))
    
    fig.add_trace(go.Bar(
        x=years,
        y=lower_values,
        name='估值下限',
        marker_color='lightblue',
        opacity=0.7
    ))
    
    # 添加中位值散点
    fig.add_trace(go.Scatter(
        x=years,
        y=median_values,
        mode='markers+text',
        name='中位估值',
        marker=dict(color='red', size=10),
        text=[f'${val:.2f}' for val in median_values],
        textposition='top center'
    ))
    
    fig.update_layout(
        title='前瞻估值分析',
        xaxis_title='财年',
        yaxis_title='股价 (USD)',
        barmode='overlay',
        height=500,
        showlegend=True
    )
    
    return fig

def create_pe_trend_chart(price_data, eps):
    """创建PE趋势图表"""
    if eps is None or eps <= 0:
        return None
    
    pe_values = price_data['Close'] / eps
    pe_values = pe_values.dropna()
    
    if pe_values.empty:
        return None
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=pe_values.index,
        y=pe_values.values,
        mode='lines',
        name='每日PE',
        line=dict(color='blue', width=2)
    ))
    
    # 添加均值线
    pe_mean = pe_values.mean()
    fig.add_hline(y=pe_mean, line_dash="dash", line_color="red", 
                  annotation_text=f"均值: {pe_mean:.2f}")
    
    fig.update_layout(
        title='PE趋势分析（过去12个月）',
        xaxis_title='日期',
        yaxis_title='PE倍数',
        height=400
    )
    
    return fig

def main():
    # 标题
    st.markdown('<h1 class="main-header">📊 PE估值计算器</h1>', unsafe_allow_html=True)
    
    # 侧边栏输入
    st.sidebar.header("📝 输入参数")
    
    # 股票代码输入
    ticker = st.sidebar.text_input("股票代码", value="NVDA", help="输入美股代码，如 NVDA, AAPL, GOOGL")
    
    if not ticker:
        st.warning("请输入股票代码")
        return
    
    # 初始化计算器
    calculator = PECalculator()
    
    # API密钥设置
    st.sidebar.markdown("---")
    st.sidebar.write("🔑 API设置")
    st.sidebar.write("设置Financial Modeling Prep API密钥以获取实时行业PE数据")
    fmp_api_key = st.sidebar.text_input(
        "Financial Modeling Prep API密钥", 
        value=st.session_state.get('fmp_api_key', ''),
        type="password",
        help="获取免费API密钥: https://site.financialmodelingprep.com/developer/docs/"
    )
    if fmp_api_key:
        st.session_state['fmp_api_key'] = fmp_api_key
        st.sidebar.success("✅ API密钥已保存")
    
    # 数据刷新选项
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 数据更新")
    force_refresh = st.sidebar.checkbox("强制刷新所有数据", help="忽略缓存，重新获取最新数据")
    
    # 缓存管理
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 缓存管理")
    
    # 显示缓存统计
    cache_stats = calculator.cache_manager.get_cache_stats()
    st.sidebar.write(f"缓存文件数: {cache_stats['total_files']}")
    st.sidebar.write(f"缓存大小: {cache_stats['total_size_mb']:.2f} MB")
    
    # 清理缓存按钮
    if st.sidebar.button("🗑️ 清理过期缓存"):
        cleaned = calculator.cache_manager.cleanup_cache()
        st.sidebar.success(f"已清理 {cleaned} 个过期缓存文件")
        st.rerun()
    
    if st.sidebar.button("🗑️ 清理所有缓存"):
        calculator.cache_manager.clear_all_cache()
        st.sidebar.success("已清理所有缓存文件")
        st.rerun()
    
    # 获取数据按钮
    if st.sidebar.button("🔄 获取数据", type="primary"):
        with st.spinner("正在获取股票数据..."):
            # 获取股票数据
            price_data, stock_info = calculator.get_stock_data(ticker.upper(), force_refresh=force_refresh)
            
            if price_data is None:
                st.error("无法获取股票数据，请检查股票代码")
                return
            
            # 获取EPS数据
            eps_ttm = calculator.get_eps_ttm(ticker.upper(), force_refresh=force_refresh)
            
            if eps_ttm is None or eps_ttm <= 0:
                st.error("无法获取有效的EPS数据")
                return
            
            # 获取行业平均PE数据
            fmp_api_key = st.session_state.get('fmp_api_key', None)
            industry_data = calculator.get_industry_pe_data(ticker.upper(), force_refresh=force_refresh, api_key=fmp_api_key)
            
            # 存储到session state
            st.session_state.price_data = price_data
            st.session_state.stock_info = stock_info
            st.session_state.eps_ttm = eps_ttm
            st.session_state.ticker = ticker.upper()
            st.session_state.industry_data = industry_data
    
    # 检查是否有数据
    if 'price_data' not in st.session_state:
        st.info("请点击'获取数据'按钮开始分析")
        return
    
    price_data = st.session_state.price_data
    stock_info = st.session_state.stock_info
    eps_ttm = st.session_state.eps_ttm
    ticker = st.session_state.ticker
    industry_data = st.session_state.get('industry_data', {})
    
    # 显示基本信息
    st.subheader(f"📈 {ticker} - {stock_info.get('longName', 'N/A')}")
    
    # 显示行业信息
    if industry_data:
        industry_name = industry_data.get('industry_name', 'N/A')
        sector_name = industry_data.get('sector_name', 'N/A')
        st.markdown(f"**🏭 行业:** {industry_name} | **📊 板块:** {sector_name}")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        current_price = price_data['Close'].iloc[-1]
        st.metric("当前股价", f"${current_price:.2f}")
    
    with col2:
        st.metric("TTM EPS", f"${eps_ttm:.2f}")
    
    with col3:
        current_pe = current_price / eps_ttm
        st.metric("当前PE", f"{current_pe:.2f}")
    
    with col4:
        market_cap = stock_info.get('marketCap', 0)
        if market_cap > 1e12:
            cap_str = f"${market_cap/1e12:.2f}T"
        elif market_cap > 1e9:
            cap_str = f"${market_cap/1e9:.2f}B"
        else:
            cap_str = f"${market_cap/1e6:.2f}M"
        st.metric("市值", cap_str)
    
    # 行业PE对比
    if industry_data and industry_data.get('industry_pe'):
        st.subheader("🏭 行业PE对比分析")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            current_pe = current_price / eps_ttm
            st.metric("当前PE", f"{current_pe:.2f}")
        
        with col2:
            industry_pe = industry_data.get('industry_pe', 0)
            pe_diff = current_pe - industry_pe
            delta_color = "normal" if abs(pe_diff) < 2 else ("inverse" if pe_diff > 0 else "normal")
            st.metric(
                "行业平均PE", 
                f"{industry_pe:.2f}", 
                delta=f"{pe_diff:+.2f}",
                delta_color=delta_color
            )
        
        with col3:
            market_pe = industry_data.get('market_pe')
            if market_pe is not None:
                market_diff = current_pe - market_pe
                delta_color = "normal" if abs(market_diff) < 3 else ("inverse" if market_diff > 0 else "normal")
                st.metric(
                    "市场平均PE", 
                    f"{market_pe:.2f}", 
                    delta=f"{market_diff:+.2f}",
                    delta_color=delta_color
                )
            else:
                st.metric("市场平均PE", "N/A")
        
        with col4:
            # PE相对估值
            if industry_pe > 0:
                relative_pe = (current_pe / industry_pe - 1) * 100
                if relative_pe > 20:
                    valuation_status = "高估"
                    status_color = "🔴"
                elif relative_pe < -20:
                    valuation_status = "低估"
                    status_color = "🟢"
                else:
                    valuation_status = "合理"
                    status_color = "🟡"
                
                st.metric(
                    "相对估值", 
                    f"{status_color} {valuation_status}", 
                    delta=f"{relative_pe:+.1f}%"
                )
            else:
                st.metric("相对估值", "N/A")
        
        # PE对比说明
        st.markdown("""
        **📊 PE对比说明：**
        - **绿色 (🟢)**: 相对行业平均PE低估超过20%
        - **黄色 (🟡)**: 相对行业平均PE在±20%范围内，估值合理
        - **红色 (🔴)**: 相对行业平均PE高估超过20%
        """)
    
    # 计算PE区间
    pe_stats = calculator.calculate_pe_range(price_data, eps_ttm)
    
    if pe_stats is None:
        st.error("无法计算PE区间")
        return
    
    # PE统计信息
    st.subheader("📊 PE统计分析")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # PE趋势图
        pe_chart = create_pe_trend_chart(price_data, eps_ttm)
        if pe_chart:
            st.plotly_chart(pe_chart, use_container_width=True)
    
    with col2:
        st.markdown("**PE统计指标**")
        st.write(f"均值: {pe_stats['pe_mean']}")
        st.write(f"中位数: {pe_stats['pe_median']}")
        st.write(f"标准差: {pe_stats['pe_std']}")
        st.write(f"区间: {pe_stats['pe_lower']} – {pe_stats['pe_upper']}")
        st.write(f"最小值: {pe_stats['pe_min']}")
        st.write(f"最大值: {pe_stats['pe_max']}")
        st.write(f"数据点: {pe_stats['data_points']}")
    
    # 手动调整PE区间
    st.subheader("⚙️ 调整参数")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**PE区间调整**")
        pe_lower_adj = st.number_input("PE下限", value=float(pe_stats['pe_lower']), min_value=0.0, step=0.1)
        pe_upper_adj = st.number_input("PE上限", value=float(pe_stats['pe_upper']), min_value=0.0, step=0.1)
        pe_median_adj = st.number_input("PE中位值", value=float(pe_stats['pe_median']), min_value=0.0, step=0.1)
    
    with col2:
        st.write("**前瞻EPS调整**")
        # 检查是否需要获取前瞻EPS数据
        if 'forward_eps' not in st.session_state or force_refresh:
            forward_eps = calculator.get_forward_eps_estimates(ticker, force_refresh=force_refresh)
            st.session_state.forward_eps = forward_eps
        else:
            forward_eps = st.session_state.forward_eps
        
        eps_2025 = st.number_input("2025年EPS", value=forward_eps.get('2025') or 0.0, min_value=0.0, step=0.01, format="%.2f")
        eps_2026 = st.number_input("2026年EPS", value=forward_eps.get('2026') or 0.0, min_value=0.0, step=0.01, format="%.2f")
        eps_2027 = st.number_input("2027年EPS", value=forward_eps.get('2027') or 0.0, min_value=0.0, step=0.01, format="%.2f")
    
    # 重新计算按钮
    if st.button("🔄 重新计算估值", type="primary"):
        # 更新PE区间
        adjusted_pe_range = {
            'pe_lower': pe_lower_adj,
            'pe_upper': pe_upper_adj,
            'pe_median': pe_median_adj
        }
        
        # 更新前瞻EPS
        adjusted_forward_eps = {
            '2025': eps_2025,
            '2026': eps_2026,
            '2027': eps_2027
        }
        
        # 计算估值
        valuation_results = calculator.calculate_valuation(adjusted_forward_eps, adjusted_pe_range)
        
        if valuation_results:
            st.session_state.valuation_results = valuation_results
            st.session_state.adjusted_pe_range = adjusted_pe_range
            st.session_state.adjusted_forward_eps = adjusted_forward_eps
    
    # 显示估值结果
    if 'valuation_results' in st.session_state:
        st.subheader("🔮 前瞻估值分析")
        
        valuation_results = st.session_state.valuation_results
        
        # 估值图表
        valuation_chart = create_valuation_chart(valuation_results)
        if valuation_chart:
            st.plotly_chart(valuation_chart, use_container_width=True)
        
        # 估值表格
        st.subheader("📋 估值详情")
        
        # 创建DataFrame用于显示
        df_display = pd.DataFrame([
            {
                '财年': result['year'],
                '前瞻EPS': result['eps'],
                'PE区间': result['pe_range'],
                '估值范围': result['valuation_range'],
                'EPS来源': result['source']
            }
            for result in valuation_results
        ])
        
        st.dataframe(df_display, use_container_width=True)
        
        # 估值总结模块已移除
        


if __name__ == "__main__":
    main()