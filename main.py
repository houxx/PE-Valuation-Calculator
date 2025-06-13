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
import os
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
        self.cache_manager = CacheManager()
        
    def get_stock_data(self, ticker, force_refresh=False):
        """获取股票历史数据"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'stock_data')
            if cached_data:
                stock_data = cached_data[0]
                update_time = self.cache_manager.get_data_update_time(ticker, 'stock_data')
                return stock_data
        
        # 获取股票数据
        try:
            stock = yf.Ticker(ticker)
            stock_data = stock.history(period="5y")
            
            # 保存到缓存
            self.cache_manager.save_cache(ticker, 'stock_data', stock_data)
            
            return stock_data
        except Exception as e:
            st.error(f"获取股票数据失败: {e}")
            return None
    
    def get_eps_ttm(self, ticker, force_refresh=False):
        """获取TTM EPS数据"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'eps_ttm')
            if cached_data:
                eps_ttm = cached_data[0]
                update_time = self.cache_manager.get_data_update_time(ticker, 'eps_ttm')
                return eps_ttm
        
        # 获取EPS数据
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            eps_ttm = info.get('trailingEps', None)
            
            # 保存到缓存
            self.cache_manager.save_cache(ticker, 'eps_ttm', eps_ttm)
            
            return eps_ttm
        except Exception as e:
            st.error(f"获取EPS数据失败: {e}")
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
    
    def get_forward_eps_estimates(self, ticker, force_refresh=False):
        """获取前瞻EPS估计"""
        # 检查缓存
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'forward_eps')
            if cached_data:
                forward_eps = cached_data[0]
                return forward_eps
        
        try:
            # 获取股票信息
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # 获取当前日期
            current_date = datetime.now()
            
            # 尝试获取公司的最后财年结束日期
            try:
                if 'lastFiscalYearEnd' in info:
                    # lastFiscalYearEnd是Unix时间戳，需要转换
                    last_fiscal_year_end = datetime.fromtimestamp(info['lastFiscalYearEnd'])
                    # 获取财年年份（通常以结束年份命名）
                    fiscal_year = last_fiscal_year_end.year
                    
                    # 计算当前财年、下一财年
                    # 如果当前日期已经过了上一个财年结束日期的同一天，则当前财年为fiscal_year+1
                    current_fiscal_year = fiscal_year
                    if current_date.month > last_fiscal_year_end.month or \
                       (current_date.month == last_fiscal_year_end.month and current_date.day > last_fiscal_year_end.day):
                        current_fiscal_year += 1
                else:
                    # 如果无法获取财年信息，则使用当前日历年
                    current_fiscal_year = current_date.year
            except Exception as e:
                print(f"获取财年信息时出错: {e}")
                # 如果出错，则使用当前日历年
                current_fiscal_year = current_date.year
            
            # 创建财年标签 - 只保留当前财年和下一财年
            fy_current = f"FY{current_fiscal_year}"
            fy_next = f"FY{current_fiscal_year+1}"
            
            # 初始化前瞻EPS字典 - 只包含当前财年和下一财年
            forward_eps = {
                fy_current: None,
                fy_next: None
            }
            
            # 只使用从API获取的实际数据，不进行预测估算
            if 'forwardEps' in info and info['forwardEps'] is not None:
                forward_eps[fy_current] = info['forwardEps']
            
            # 获取trailingEps作为参考，但不用于预测
            if 'trailingEps' in info and info['trailingEps'] is not None:
                # 只记录实际的trailingEps，不用于预测
                trailing_eps = info['trailingEps']
                # 不再使用trailingEps进行预测
            
            # 缓存结果
            self.cache_manager.save_cache(ticker, 'forward_eps', forward_eps)
            return forward_eps
            
        except Exception as e:
            print(f"获取前瞻EPS估计时出错: {e}")
            # 返回空字典 - 只包含当前财年和下一财年
            current_year = datetime.now().year
            forward_eps = {
                f"FY{current_year}": None,
                f"FY{current_year+1}": None
            }
            # 即使出错也保存到缓存，避免重复查询
            self.cache_manager.save_cache(ticker, 'forward_eps', forward_eps)
            return forward_eps
    
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
                    'year': year,  # 直接使用财年标识，如'FY2023'
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
        height=400,
        xaxis=dict(
            tickformat='%Y年 %m月',  # 按年月格式化日期
            tickmode='auto',
            nticks=12,  # 大约显示12个刻度（每月一个）
            tickangle=-45,  # 倾斜角度，使标签更易读
            showgrid=True
        )
    )
    
    return fig

def main():
    st.markdown("<h1 class='main-header'>PE估值计算器</h1>", unsafe_allow_html=True)
    
    # 侧边栏设置
    st.sidebar.title("⚙️ 设置")
    
    # 检查session_state中是否已有股票代码
    if 'current_ticker' not in st.session_state:
        st.session_state.current_ticker = "AAPL"
    
    # 股票代码输入
    ticker = st.sidebar.text_input("股票代码", st.session_state.current_ticker).strip().upper()
    
    # 检测股票代码是否变更
    ticker_changed = False
    if ticker != st.session_state.current_ticker:
        ticker_changed = True
        st.session_state.current_ticker = ticker
        # 清除之前的数据
        if 'price_data' in st.session_state:
            del st.session_state.price_data
        if 'stock_info' in st.session_state:
            del st.session_state.stock_info
        if 'eps_ttm' in st.session_state:
            del st.session_state.eps_ttm
        if 'forward_eps' in st.session_state:
            del st.session_state.forward_eps
        if 'valuation_results' in st.session_state:
            del st.session_state.valuation_results
        # 自动获取新数据
        st.rerun()
    
    # 数据刷新选项
    st.sidebar.subheader("🔄 数据刷新选项")
    force_refresh = st.sidebar.checkbox("强制刷新数据（不使用缓存）")
    
    # 初始化计算器
    calculator = PECalculator()
    
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
        with st.spinner(""):
            # 获取股票数据
            stock_data = calculator.get_stock_data(ticker.upper(), force_refresh=force_refresh)
            
            if stock_data is None:
                st.error("无法获取股票数据，请检查股票代码")
                return
            
            # 获取股票信息
            try:
                # 检查缓存中是否有股票信息
                if 'stock_info' not in st.session_state or force_refresh:
                    stock = yf.Ticker(ticker.upper())
                    stock_info = stock.info
                    st.session_state.stock_info = stock_info
                else:
                    stock_info = st.session_state.stock_info
            except Exception as e:
                st.error(f"获取股票信息失败: {e}")
                return
            
            # 获取EPS数据
            eps_ttm = calculator.get_eps_ttm(ticker.upper(), force_refresh=force_refresh)
            
            if eps_ttm is None or eps_ttm <= 0:
                st.error("无法获取有效的EPS数据")
                return
            
            # 存储到session state
            st.session_state.price_data = stock_data
            st.session_state.stock_info = stock_info
            st.session_state.eps_ttm = eps_ttm
            st.session_state.ticker = ticker.upper()
    
    # 检查是否有数据
    if 'price_data' not in st.session_state:
        # 自动获取数据
        with st.spinner("正在获取数据..."):
            # 获取股票数据
            stock_data = calculator.get_stock_data(ticker.upper(), force_refresh=force_refresh)
            
            if stock_data is None:
                st.error("无法获取股票数据，请检查股票代码")
                return
            
            # 获取股票信息
            try:
                stock = yf.Ticker(ticker.upper())
                stock_info = stock.info
                st.session_state.stock_info = stock_info
            except Exception as e:
                st.error(f"获取股票信息失败: {e}")
                return
            
            # 获取EPS数据
            eps_ttm = calculator.get_eps_ttm(ticker.upper(), force_refresh=force_refresh)
            
            if eps_ttm is None or eps_ttm <= 0:
                st.error("无法获取有效的EPS数据")
                return
            
            # 获取前瞻EPS数据
            forward_eps = calculator.get_forward_eps_estimates(ticker, force_refresh=force_refresh)
            
            # 存储到session state
            st.session_state.price_data = stock_data
            st.session_state.stock_info = stock_info
            st.session_state.eps_ttm = eps_ttm
            st.session_state.forward_eps = forward_eps
            st.session_state.ticker = ticker.upper()
    
    price_data = st.session_state.price_data
    stock_info = st.session_state.stock_info
    eps_ttm = st.session_state.eps_ttm
    ticker = st.session_state.ticker
    
    # 显示基本信息
    st.subheader(f"📈 {ticker} - {stock_info.get('longName', 'N/A')}")
    
    # 显示行业信息
    if stock_info:
        industry_name = stock_info.get('industry', 'N/A')
        sector_name = stock_info.get('sector', 'N/A')
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
        
        
        # 添加PE区间调整说明 - 始终显示
        st.markdown("### 📝 自定义调整前瞻PE区间")
        
        # 简洁显示数据来源提示
        st.markdown("💡 **行业PE参考:** [Seeking Alpha](https://seekingalpha.com) (推荐)")
        
        # 创建小型下拉框，仅在需要时展开详细说明
        with st.expander("查看行业PE获取方法", expanded=False):
            # 添加行业PE获取说明
            st.markdown("""
            **Seeking Alpha 行业PE查询方法：**
            
            - 网站地址： [Seeking Alpha](https://seekingalpha.com)
            - 获取路径： 
              - 搜索股票代码 → 点击「Valuation」页签
              - 点击「Grade & Metrics」页签
              - 查看「P/E Non-GAAP (FWD)」指标
              - 页面右侧对比表中有「Sector Median」PE值
            """)
        
        pe_lower_adj = st.number_input("PE下限", value=float(pe_stats['pe_lower']), min_value=0.0, step=0.1)
        pe_upper_adj = st.number_input("PE上限", value=float(pe_stats['pe_upper']), min_value=0.0, step=0.1)
        pe_median_adj = st.number_input("PE中位值", value=float(pe_stats['pe_median']), min_value=0.0, step=0.1)
    
    with col2:
       
        
        # 添加EPS获取说明 - 始终显示
        st.markdown("### 📝 自定义调整EPS预测数据")
        
        # 简洁显示数据来源提示
        st.markdown("💡 **数据来源:** [Seeking Alpha](https://seekingalpha.com) (推荐) | [Yahoo Finance](https://finance.yahoo.com) | 公司财报")
        
        # 创建小型下拉框，仅在需要时展开详细说明
        with st.expander("查看详细获取方法", expanded=False):
            # 添加数据获取说明
            st.markdown("""
            **推荐数据来源：**
            
             **Seeking Alpha** (推荐)
               - 搜索股票代码 → Earnings → Earnings Estimates
               - 查看"EPS Estimate"表格中的未来年份预测
            
            **注意：** 请确保使用最新的分析师一致预期数据，避免使用过时信息
            """)
        
        # 检查是否需要获取前瞻EPS数据
        if 'forward_eps' not in st.session_state or force_refresh:
            forward_eps = calculator.get_forward_eps_estimates(ticker, force_refresh=force_refresh)
            st.session_state.forward_eps = forward_eps
        else:
            forward_eps = st.session_state.forward_eps
        
        # 获取财年键列表
        fiscal_years = list(forward_eps.keys())
        fiscal_years.sort()  # 确保按年份排序
        
        # 使用实际财年信息作为标签
        if len(fiscal_years) >= 1:
            eps_fy_current = st.number_input(f"{fiscal_years[0]} EPS (当前财年)", 
                                            value=forward_eps.get(fiscal_years[0]) or 0.0, 
                                            min_value=0.0, step=0.01, format="%.2f")
        else:
            eps_fy_current = st.number_input("当前财年 EPS", value=0.0, min_value=0.0, step=0.01, format="%.2f")
            
        if len(fiscal_years) >= 2:
            eps_fy_next = st.number_input(f"{fiscal_years[1]} EPS (下一财年)", 
                                        value=forward_eps.get(fiscal_years[1]) or 0.0, 
                                        min_value=0.0, step=0.01, format="%.2f")
        else:
            eps_fy_next = st.number_input("下一财年 EPS", value=0.0, min_value=0.0, step=0.01, format="%.2f")
            
        # 移除后年财年的输入框
    
    # 重新计算按钮
    if st.button("🔄 重新计算估值", type="primary"):
        # 更新PE区间
        adjusted_pe_range = {
            'pe_lower': pe_lower_adj,
            'pe_upper': pe_upper_adj,
            'pe_median': pe_median_adj
        }
        
        # 获取财年键列表
        fiscal_years = list(forward_eps.keys())
        fiscal_years.sort()  # 确保按年份排序
        
        # 更新前瞻EPS
        adjusted_forward_eps = {}
        
        # 根据可用的财年键更新EPS值 - 只包含当前财年和下一财年
        if len(fiscal_years) >= 1:
            adjusted_forward_eps[fiscal_years[0]] = eps_fy_current
        if len(fiscal_years) >= 2:
            adjusted_forward_eps[fiscal_years[1]] = eps_fy_next
        
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