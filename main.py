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

# 初始化API调用计数器
if 'api_call_count' not in st.session_state:
    # 不再直接重置为0，而是检查是否需要按日期重置
    today = datetime.now().date()
    if 'api_call_date' in st.session_state and st.session_state.api_call_date == today:
        # 如果是同一天，保持计数器不变
        pass
    else:
        # 如果是新的一天或首次运行，重置计数器
        st.session_state.api_call_count = 0
        st.session_state.api_call_date = today
        st.session_state.rate_limited = False  # 重置速率限制标志
        st.session_state.using_cached_data = False  # 是否正在使用缓存数据

# API调用计数函数
def increment_api_call_count():
    # 检查是否需要重置计数（新的一天）
    today = datetime.now().date()
    if 'api_call_date' not in st.session_state or st.session_state.api_call_date != today:
        st.session_state.api_call_count = 0
        st.session_state.api_call_date = today
        st.session_state.rate_limited = False  # 重置速率限制标志
    
    # 增加计数
    st.session_state.api_call_count += 1
    
    # 调整API限制阈值，降低到30次以避免触发yfinance限制
    if st.session_state.api_call_count >= 50:
        st.session_state.rate_limited = True
    
    return st.session_state.api_call_count

# 安全的API调用函数，支持自动回退到缓存
def safe_api_call(func, *args, **kwargs):
    """安全的API调用，遇到错误时自动回退到缓存数据"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "too many requests" in error_msg or "429" in error_msg:
            st.session_state.rate_limited = True
            st.session_state.using_cached_data = True
            raise e
        else:
            raise e

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

class 滚动PECalculator:
    def __init__(self):
        self.ticker = None
        self.stock_data = None
        self.eps_ttm = None
        self.cache_manager = CacheManager()
        
    def get_stock_data(self, ticker, force_refresh=False):
        """获取股票历史数据，支持缓存回退"""
        # 优先检查缓存（不强制刷新时）
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'stock_data', allow_expired=False)
            if cached_data:
                stock_data, metadata = cached_data
                return stock_data, metadata
        
        # 尝试获取新数据
        try:
            # 检查是否已达到API调用限制
            if 'rate_limited' in st.session_state and st.session_state.rate_limited:
                # 尝试使用过期的缓存数据
                cached_data = self.cache_manager.load_cache(ticker, 'stock_data', allow_expired=True)
                if cached_data:
                    st.session_state.using_cached_data = True
                    return cached_data
                else:
                    st.error("已达到API调用限制且无可用缓存数据")
                    return None, None
                
            stock = yf.Ticker(ticker)
            increment_api_call_count()  # 增加API调用计数
            stock_data = safe_api_call(stock.history, period="1y")
            
            # 保存到缓存
            self.cache_manager.save_cache(ticker, 'stock_data', stock_data)
            
            return stock_data, None
        except Exception as e:
            # 如果错误信息包含速率限制相关内容，设置速率限制标志
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "too many requests" in error_msg or "429" in error_msg:
                st.session_state.rate_limited = True
                st.session_state.using_cached_data = True
                
                # 尝试使用过期的缓存数据
                cached_data = self.cache_manager.load_cache(ticker, 'stock_data', allow_expired=True)
                if cached_data:
                    st.warning(f"API调用受限，正在使用缓存数据")
                    return cached_data
                else:
                    st.error("API调用受限且无可用缓存数据")
                    return None, None
            
            st.error(f"获取股票数据失败: {e}")
            return None, None
    
    def get_eps_ttm(self, ticker, force_refresh=False):
        """获取TTM EPS数据，支持缓存回退"""
        # 优先检查缓存（不强制刷新时）
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'eps_ttm', allow_expired=False)
            if cached_data:
                eps_ttm, metadata = cached_data
                return eps_ttm, metadata
        
        # 尝试获取新数据
        try:
            # 检查是否已达到API调用限制
            if 'rate_limited' in st.session_state and st.session_state.rate_limited:
                # 尝试使用过期的缓存数据
                cached_data = self.cache_manager.load_cache(ticker, 'eps_ttm', allow_expired=True)
                if cached_data:
                    st.session_state.using_cached_data = True
                    return cached_data
                else:
                    st.error("已达到API调用限制且无可用缓存数据")
                    return None, None
                
            stock = yf.Ticker(ticker)
            increment_api_call_count()  # 增加API调用计数
            info = stock.info  # stock.info是属性，不是方法，不需要通过safe_api_call调用
            eps_ttm = info.get('trailingEps', None)
            
            # 保存到缓存
            self.cache_manager.save_cache(ticker, 'eps_ttm', eps_ttm)
            
            return eps_ttm, None
        except Exception as e:
            # 如果错误信息包含速率限制相关内容，设置速率限制标志
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "too many requests" in error_msg or "429" in error_msg:
                st.session_state.rate_limited = True
                st.session_state.using_cached_data = True
                
                # 尝试使用过期的缓存数据
                cached_data = self.cache_manager.load_cache(ticker, 'eps_ttm', allow_expired=True)
                if cached_data:
                    st.warning(f"API调用受限，正在使用缓存数据")
                    return cached_data
                else:
                    st.error("API调用受限且无可用缓存数据")
                    return None, None
            
            st.error(f"获取EPS数据失败: {e}")
            return None, None
    
    def calculate_pe_range(self, price_data, eps):
        """计算滚动PE区间"""
        if eps is None or eps <= 0:
            return None
        
        pe_values = price_data['Close'] / eps  # 计算滚动PE值
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
        """获取前瞻EPS估计，支持缓存回退"""
        # 优先检查缓存（不强制刷新时）
        if not force_refresh:
            cached_data = self.cache_manager.load_cache(ticker, 'forward_eps', allow_expired=False)
            if cached_data:
                forward_eps, metadata = cached_data
                return forward_eps, metadata
        
        try:
            # 检查缓存中是否有股票信息
            if not force_refresh:
                cached_info = self.cache_manager.load_cache(ticker, 'stock_info', allow_expired=False)
                if cached_info:
                    info, metadata = cached_info
                else:
                    # 尝试获取新的股票信息
                    if 'rate_limited' in st.session_state and st.session_state.rate_limited:
                        cached_info = self.cache_manager.load_cache(ticker, 'stock_info', allow_expired=True)
                        if cached_info:
                            info, metadata = cached_info
                            st.session_state.using_cached_data = True
                        else:
                            raise Exception("API调用受限且无可用缓存数据")
                    else:
                        stock = yf.Ticker(ticker)
                        increment_api_call_count()  # 增加API调用计数
                        info = stock.info  # stock.info是属性，不是方法
                        # 保存到缓存
                        self.cache_manager.save_cache(ticker, 'stock_info', info)
            else:
                # 强制刷新
                stock = yf.Ticker(ticker)
                increment_api_call_count()  # 增加API调用计数
                info = stock.info  # stock.info是属性，不是方法
                # 保存到缓存
                self.cache_manager.save_cache(ticker, 'stock_info', info)
            
            # 获取当前日期
            current_date = datetime.now()
            
            # 尝试获取公司的最新财报日期和财年
            try:
                # 首先尝试获取最新财报日期
                if 'earningsDate' in info and info['earningsDate'] is not None:
                    # earningsDate是Unix时间戳，需要转换
                    earnings_date = datetime.fromtimestamp(info['earningsDate'])
                    # 使用最新财报发布日期的年份作为当前财年
                    current_fiscal_year = earnings_date.year
                # 如果没有earningsDate，尝试使用nextEarningsDate
                elif 'nextEarningsDate' in info and info['nextEarningsDate'] is not None:
                    # 下一次财报日期可能是字符串格式，需要转换
                    try:
                        next_earnings_date = datetime.strptime(info['nextEarningsDate'], '%Y-%m-%d')
                        # 使用下一次财报日期的年份作为当前财年
                        current_fiscal_year = next_earnings_date.year
                    except:
                        # 如果转换失败，回退到lastFiscalYearEnd逻辑
                        if 'lastFiscalYearEnd' in info:
                            last_fiscal_year_end = datetime.fromtimestamp(info['lastFiscalYearEnd'])
                            fiscal_year = last_fiscal_year_end.year
                            
                            # 计算当前财年
                            current_fiscal_year = fiscal_year
                            if current_date.month > last_fiscal_year_end.month or \
                               (current_date.month == last_fiscal_year_end.month and current_date.day > last_fiscal_year_end.day):
                                current_fiscal_year += 1
                        else:
                            # 如果无法获取财年信息，则使用当前日历年
                            current_fiscal_year = current_date.year
                # 如果没有财报日期信息，回退到lastFiscalYearEnd逻辑
                elif 'lastFiscalYearEnd' in info:
                    last_fiscal_year_end = datetime.fromtimestamp(info['lastFiscalYearEnd'])
                    fiscal_year = last_fiscal_year_end.year
                    
                    # 计算当前财年
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
            return forward_eps, None
            
        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "too many requests" in error_msg or "429" in error_msg:
                st.session_state.rate_limited = True
                st.session_state.using_cached_data = True
                
                # 尝试使用过期的缓存数据
                cached_data = self.cache_manager.load_cache(ticker, 'forward_eps', allow_expired=True)
                if cached_data:
                    st.warning(f"API调用受限，正在使用缓存数据")
                    return cached_data
            
            print(f"获取前瞻EPS估计时出错: {e}")
            # 返回空字典 - 只包含当前财年和下一财年
            current_year = datetime.now().year
            forward_eps = {
                f"FY{current_year}": None,
                f"FY{current_year+1}": None
            }
            # 即使出错也保存到缓存，避免重复查询
            self.cache_manager.save_cache(ticker, 'forward_eps', forward_eps)
            return forward_eps, None
    
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
                    'valuation_range': f"${valuation_lower:.2f} – （中位：{valuation_median:.2f}） – {valuation_upper:.2f}",
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
    
    # 创建数值索引作为x轴位置
    x_positions = list(range(len(years)))
    
    # 创建适当的财年标签
    if len(years) == 1:
        fiscal_labels = ["当前财年"]
    elif len(years) == 2:
        fiscal_labels = ["当前财年", "下一财年"]
    else:
        fiscal_labels = [f"财年{i+1}" for i in range(len(years))]
    
    fig = go.Figure()
    
    # 添加估值区间柱状图
    fig.add_trace(go.Bar(
        x=x_positions,  # 使用数值索引而不是year字符串
        y=upper_values,
        name='估值上限',
        marker_color='#F4BB40',  # 修改为橙色
        opacity=1,
        width=0.4  # 减小柱子宽度
    ))
    
    fig.add_trace(go.Bar(
        x=x_positions,  # 使用数值索引而不是year字符串
        y=lower_values,
        name='估值下限',
        marker_color='#2CCB7B',  # 修改为绿色
        opacity=1,
        width=0.4  # 减小柱子宽度
    ))
    
    # 添加中位值线 - 修改为每个柱状图上的独立横线
    for i, year in enumerate(years):
        # 添加中位值横线
        # 使用索引i作为数值位置，而不是尝试转换year字符串
        x_position = i  # 使用索引作为x轴位置
        # 计算横线的起点和终点，使其宽度与柱状图相似
        x_offset = 0.2  # 修改为0.2，使横线宽度与柱状图宽度一致
        fig.add_shape(
            type="line",
            x0=x_position - x_offset,  # 左侧起点
            y0=median_values[i],
            x1=x_position + x_offset,  # 右侧终点
            y1=median_values[i],
            line=dict(color="white", width=3),
        )
        
        # 添加中位值文本
        fig.add_annotation(
            x=x_position,  # 使用索引位置而不是year字符串
            y=median_values[i],
            text=f'${median_values[i]:.2f}',
            showarrow=False,
            font=dict(family='DIN', size=32, color='white', weight='bold'),  # 增大字体并加粗
            yshift=40,  # 向上移动文字
            xshift=0
        )
    
    # 添加标签
    for i, year in enumerate(years):
        # 使用索引i作为x轴位置
        x_position = i
        # 添加上限标签
        fig.add_annotation(
            x=x_position,  # 使用索引位置而不是year字符串
            y=upper_values[i],
            text=f'${upper_values[i]:.2f}',
            showarrow=False,
            font=dict(family='DIN', size=21, color='#E8AB29'),  # 使用与柱子相同的颜色，字体大小缩小一倍
            yshift=10,  # 向上移动文字，避免与柱子重叠
            xshift=130,  # 减小右移距离，使标签紧贴柱状图右侧
            xanchor='left'  # 左对齐，使标签最左边与柱状图最右边对齐
        )
        
        # 添加下限标签
        fig.add_annotation(
            x=x_position,  # 使用索引位置而不是year字符串
            y=lower_values[i],
            text=f'${lower_values[i]:.2f}',
            showarrow=False,
            font=dict(family='DIN', size=21, color='#2CCB7B'),  # 使用与柱子相同的颜色，字体大小缩小一倍
            yshift=10,  # 向上移动文字，避免与柱子重叠
            xshift=130,  # 减小右移距离，使标签紧贴柱状图右侧
            xanchor='left'  # 左对齐，使标签最左边与柱状图最右边对齐
        )
    
    # 设置x轴刻度为年份标签
    fig.update_layout(
        title='前瞻估值分析',
        xaxis=dict(
            title='财年',
            tickmode='array',
            tickvals=x_positions,  # 使用数值索引位置
            ticktext=fiscal_labels  # 使用新的财年标签
        ),
        yaxis_title='股价 (USD)',
        barmode='overlay',
        height=500,
        width=800,  # 设置固定宽度以与上面的文字保持一致
        showlegend=True
    )
    
    return fig

def create_pe_trend_chart(price_data, eps, cache_warning=""):
    """创建滚动PE趋势图表"""
    if eps is None or eps <= 0:
        return None
    
    pe_values = price_data['Close'] / eps  # 计算滚动PE值
    pe_values = pe_values.dropna()
    
    if pe_values.empty:
        return None
    
    # 计算PE统计值
    pe_mean = pe_values.mean()
    pe_std = pe_values.std()
    pe_lower = max(0, pe_mean - pe_std)
    pe_upper = pe_mean + pe_std
    current_pe = pe_values.iloc[-1]
    
    fig = go.Figure()
    
    # 添加滚动PE趋势线
    fig.add_trace(go.Scatter(
        x=pe_values.index,
        y=pe_values.values,
        mode='lines',
        name='每日滚动PE',
        line=dict(color='#4285F4', width=2)
    ))
    
    # 添加均值线
    fig.add_hline(y=pe_mean, line_dash='dash', line_color='#F4BB40', 
                  annotation=dict(
                      text=f'均值: {pe_mean:.2f}',
                      font=dict(size=17),
                      align='right',
                      xshift=90,  # 增加右侧偏移量，移到红框标记的位置
                      yshift=0
                  ))
    


    # 添加当前PE标记
    fig.add_trace(go.Scatter(
        x=[pe_values.index[-1]],
        y=[current_pe],
        mode='markers+text',
        marker=dict(color='#66BED9', size=10),
        text=f'当前滚动PE: {current_pe:.2f}',
        textposition='top center',
        name='当前滚动PE'
    ))
    
    # 添加缓存数据提示到图表标题
    chart_title = '滚动PE趋势分析（过去12个月）'
    if cache_warning:
        chart_title += cache_warning
    
    fig.update_layout(
        title=chart_title,
    xaxis_title='日期',
    yaxis_title='滚动PE倍数',
        height=400,
        width=800,  # 设置固定宽度以与上面的文字保持一致
        xaxis=dict(
            tickformat='%Y年 %m月',  # 按年月格式化日期
            tickmode='auto',
            nticks=12,  # 大约显示12个刻度（每月一个）
            tickangle=-30,  # 倾斜角度，使标签更易读
            showgrid=True
        )
    )
    
    return fig

def main():
    # 在右上角显示API调用计数和速率限制状态
    rate_limited_status = "⚠️ 已限制" if 'rate_limited' in st.session_state and st.session_state.rate_limited else ""
    rate_limited_color = "color: red;" if 'rate_limited' in st.session_state and st.session_state.rate_limited else ""
    
    st.markdown(
        f"<div style='position: absolute; top: 0.5rem; right: 1rem; z-index: 1000; font-size: 0.8rem; {rate_limited_color}'>API调用次数: {st.session_state.api_call_count}/50 {rate_limited_status}</div>",
        unsafe_allow_html=True
    )
    
    st.markdown("<h1 class='main-header'>PE估值计算器</h1>", unsafe_allow_html=True)
    
    # 初始化计算器
    calculator = 滚动PECalculator()
    
    # 自动清理过期缓存
    cleaned = calculator.cache_manager.cleanup_cache()
    if cleaned > 0:
        st.sidebar.info(f"已自动清理 {cleaned} 个过期缓存文件")
    
    # 侧边栏设置
    st.sidebar.title("⚙️ 设置")
    
    # 显示API调用状态
    if 'api_call_count' in st.session_state:
        if st.session_state.rate_limited:
            st.sidebar.error(f"⚠️ API调用已达限制 ({st.session_state.api_call_count}/50)")
        else:
            st.sidebar.info(f"📡 今日API调用: {st.session_state.api_call_count}/50")
    
    # 缓存状态显示
    st.sidebar.subheader("💾 缓存状态")
    if 'using_cached_data' in st.session_state and st.session_state.using_cached_data:
        st.sidebar.warning("🔄 当前使用缓存数据")
    else:
        st.sidebar.success("🌐 当前使用实时数据")
    
    # 如果有股票代码，显示该股票的缓存状态
    if 'ticker' in st.session_state and st.session_state.ticker:
        cache_status = calculator.cache_manager.get_cache_status_summary(st.session_state.ticker)
        if cache_status and 'data_status' in cache_status:
            st.sidebar.write("**当前股票缓存状态:**")
            data_type_names = {
                'stock_data': '股价数据',
                'eps_ttm': 'EPS数据', 
                'forward_eps': '前瞻EPS',
                'stock_info': '股票信息'
            }
            for data_type, status in cache_status['data_status'].items():
                display_name = data_type_names.get(data_type, data_type)
                if status and status.get('update_time'):
                    if status.get('is_expired', True):
                        # 计算缓存天数
                        try:
                            from datetime import datetime
                            update_time = datetime.strptime(status['update_time'], '%Y-%m-%d %H:%M:%S')
                            days_old = (datetime.now() - update_time).days
                            st.sidebar.write(f"📄 {display_name}: 已过期 ({days_old}天前)")
                        except:
                            st.sidebar.write(f"📄 {display_name}: 已过期")
                    else:
                        try:
                            from datetime import datetime
                            update_time = datetime.strptime(status['update_time'], '%Y-%m-%d %H:%M:%S')
                            days_old = (datetime.now() - update_time).days
                            st.sidebar.write(f"✅ {display_name}: 有效 ({days_old}天前)")
                        except:
                            st.sidebar.write(f"✅ {display_name}: 有效")
                else:
                    st.sidebar.write(f"❌ {display_name}: 无缓存")
    
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
        # 清除EPS输入数据
        if 'eps_fy_current_input' in st.session_state:
            del st.session_state.eps_fy_current_input
        if 'eps_fy_next_input' in st.session_state:
            del st.session_state.eps_fy_next_input
        # 自动获取新数据
        st.rerun()
    
    # 数据刷新选项
    st.sidebar.subheader("🔄 数据刷新选项")
    force_refresh = st.sidebar.checkbox("强制刷新数据（不使用缓存）")
    
    # 缓存管理
    st.sidebar.markdown("---")
    st.sidebar.subheader("🗂️ 缓存管理")
    
    # 显示缓存统计
    cache_stats = calculator.cache_manager.get_cache_stats()
    st.sidebar.write(f"缓存文件数: {cache_stats['total_files']}")
    st.sidebar.write(f"缓存大小: {cache_stats['total_size_mb']:.2f} MB")
    
    # 清理缓存按钮
    if st.sidebar.button("🗑️ 清理损坏的缓存文件"):
        cleaned = calculator.cache_manager.cleanup_cache()
        st.sidebar.success(f"已清理 {cleaned} 个损坏的缓存文件")
        st.rerun()
    
    if st.sidebar.button("🗑️ 清理所有缓存"):
        cleaned = calculator.cache_manager.clear_all_cache()
        st.sidebar.success(f"已清理 {cleaned} 个缓存文件")
        st.rerun()
        
    # 速率限制管理
    st.sidebar.markdown("---")
    st.sidebar.subheader("🚦 API限制管理")
    
    # 显示当前API调用状态
    rate_limited = 'rate_limited' in st.session_state and st.session_state.rate_limited
    status_color = "🔴" if rate_limited else "🟢"
    status_text = "已限制" if rate_limited else "正常"
    st.sidebar.write(f"API状态: {status_color} {status_text}")
    st.sidebar.write(f"今日调用次数: {st.session_state.api_call_count}")
    
    # 重置API限制按钮
    if rate_limited and st.sidebar.button("🔄 重置API限制"):
        st.session_state.rate_limited = False
        st.sidebar.success("已重置API限制状态")
        st.rerun()
    
    # 获取数据按钮
    if st.sidebar.button("🔄 获取数据", type="primary"):
        st.session_state.using_cached_data = False  # 重置缓存使用状态
        with st.spinner(""):
            # 获取股票数据
            stock_data_result = calculator.get_stock_data(ticker.upper(), force_refresh=force_refresh)
            
            if stock_data_result[0] is None:
                st.error("无法获取股票数据，请检查股票代码")
                return
            stock_data, stock_metadata = stock_data_result
            
            # 获取股票信息
            try:
                # 检查缓存中是否有股票信息
                cached_info = calculator.cache_manager.load_cache(ticker.upper(), 'stock_info')
                if cached_info and not force_refresh:
                    stock_info = cached_info[0]
                else:
                    # 检查是否已达到API调用限制
                    if 'rate_limited' in st.session_state and st.session_state.rate_limited:
                        st.error("已达到API调用限制，请稍后再试或使用缓存数据")
                        return
                        
                    stock = yf.Ticker(ticker.upper())
                    increment_api_call_count()  # 增加API调用计数
                    stock_info = stock.info
                    # 保存到缓存
                    calculator.cache_manager.save_cache(ticker.upper(), 'stock_info', stock_info)
                st.session_state.stock_info = stock_info
            except Exception as e:
                st.error(f"获取股票信息失败: {e}")
                return
            
            # 获取EPS数据
            eps_result = calculator.get_eps_ttm(ticker.upper(), force_refresh=force_refresh)
            
            if eps_result[0] is None or eps_result[0] <= 0:
                st.error("无法获取有效的EPS数据")
                return
            eps_ttm, eps_metadata = eps_result
            
            # 存储到session state
            st.session_state.price_data = stock_data
            st.session_state.stock_info = stock_info
            st.session_state.eps_ttm = eps_ttm
            st.session_state.ticker = ticker.upper()
            st.session_state.stock_metadata = stock_metadata
            st.session_state.eps_metadata = eps_metadata
    
    # 检查是否有数据
    if 'price_data' not in st.session_state:
        # 自动获取数据
        st.session_state.using_cached_data = False  # 重置缓存使用状态
        with st.spinner("正在获取数据..."):
            # 获取股票数据
            stock_data_result = calculator.get_stock_data(ticker.upper(), force_refresh=force_refresh)
            
            if stock_data_result[0] is None:
                st.error("无法获取股票数据，请检查股票代码")
                return
            stock_data, stock_metadata = stock_data_result
            
            # 获取股票信息
            try:
                # 检查缓存中是否有股票信息
                cached_info = calculator.cache_manager.load_cache(ticker.upper(), 'stock_info')
                if cached_info and not force_refresh:
                    stock_info = cached_info[0]
                else:
                    # 检查是否已达到API调用限制
                    if 'rate_limited' in st.session_state and st.session_state.rate_limited:
                        st.error("已达到API调用限制，请稍后再试或使用缓存数据")
                        return
                        
                    stock = yf.Ticker(ticker.upper())
                    increment_api_call_count()  # 增加API调用计数
                    stock_info = stock.info
                    # 保存到缓存
                    calculator.cache_manager.save_cache(ticker.upper(), 'stock_info', stock_info)
                st.session_state.stock_info = stock_info
            except Exception as e:
                st.error(f"获取股票信息失败: {e}")
                return
            
            # 获取EPS数据
            eps_result = calculator.get_eps_ttm(ticker.upper(), force_refresh=force_refresh)
            
            if eps_result[0] is None or eps_result[0] <= 0:
                st.error("无法获取有效的EPS数据")
                return
            eps_ttm, eps_metadata = eps_result
            
            # 获取前瞻EPS数据
            forward_eps_result = calculator.get_forward_eps_estimates(ticker, force_refresh=force_refresh)
            forward_eps, forward_eps_metadata = forward_eps_result
            
            # 存储到session state
            st.session_state.price_data = stock_data
            st.session_state.stock_info = stock_info
            st.session_state.eps_ttm = eps_ttm
            st.session_state.forward_eps = forward_eps
            st.session_state.ticker = ticker.upper()
            st.session_state.stock_metadata = stock_metadata
            st.session_state.eps_metadata = eps_metadata
            st.session_state.forward_eps_metadata = forward_eps_metadata
    
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
        st.metric("当前滚动PE", f"{current_pe:.2f}")
    
    with col4:
        market_cap = stock_info.get('marketCap', 0)
        if market_cap > 1e12:
            cap_str = f"${market_cap/1e12:.2f}T"
        elif market_cap > 1e9:
            cap_str = f"${market_cap/1e9:.2f}B"
        else:
            cap_str = f"${market_cap/1e6:.2f}M"
        st.metric("市值", cap_str)
    
    # 计算滚动PE区间
    pe_stats = calculator.calculate_pe_range(price_data, eps_ttm)
    
    if pe_stats is None:
        st.error("无法计算滚动PE区间")
        return
    
    # 滚动PE统计信息
    # 检查是否使用了缓存数据并添加提示
    cache_warning = ""
    if ('using_cached_data' in st.session_state and st.session_state.using_cached_data) or \
       (st.session_state.get('stock_metadata') and st.session_state.stock_metadata.get('is_expired')) or \
       (st.session_state.get('eps_metadata') and st.session_state.eps_metadata.get('is_expired')):
        # 获取最旧的数据时间作为提示
        oldest_date = None
        if st.session_state.get('stock_metadata') and st.session_state.stock_metadata.get('last_updated'):
            oldest_date = st.session_state.stock_metadata['last_updated']
        if st.session_state.get('eps_metadata') and st.session_state.eps_metadata.get('last_updated'):
            eps_date = st.session_state.eps_metadata['last_updated']
            if oldest_date is None or eps_date < oldest_date:
                oldest_date = eps_date
        
        if oldest_date:
            from datetime import datetime
            if isinstance(oldest_date, str):
                oldest_date = datetime.fromisoformat(oldest_date.replace('Z', '+00:00'))
            days_old = (datetime.now(oldest_date.tzinfo) - oldest_date).days
            cache_warning = f" ⚠️ (使用{days_old}天前的缓存数据)"
    
    st.subheader(f"📊 滚动PE统计分析{cache_warning}")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # 滚动PE趋势图
        pe_chart = create_pe_trend_chart(price_data, eps_ttm, cache_warning)
        if pe_chart:
            st.plotly_chart(pe_chart, use_container_width=True)
    
    with col2:
        st.markdown("**滚动PE统计指标**")
        st.write(f"均值: {pe_stats['pe_mean']}")
        st.write(f"中位数: {pe_stats['pe_median']}")
        st.write(f"标准差: {pe_stats['pe_std']}")
        st.write(f"区间: {pe_stats['pe_lower']} – {pe_stats['pe_upper']}")
        st.write(f"最小值: {pe_stats['pe_min']}")
        st.write(f"最大值: {pe_stats['pe_max']}")
        st.write(f"数据点: {pe_stats['data_points']}")
    
    # 手动调整PE区间
    st.subheader("⚙️ 估值计算")
    
    col1, col2 = st.columns(2)
    
    with col1:
        
        
        # 添加滚动PE区间调整说明 - 始终显示
        st.markdown("#### 📝 自定义调整前瞻滚动PE区间")
        
        # 简洁显示数据来源提示
        st.markdown("💡 **行业滚动PE参考:** [Seeking Alpha](https://seekingalpha.com) (推荐)")
        
        # 创建小型下拉框，仅在需要时展开详细说明
        with st.expander("查看行业滚动PE获取方法", expanded=False):
            # 添加行业PE获取说明
            st.markdown("""
            **Seeking Alpha 行业滚动PE查询方法：**
            
            - 获取路径： 
              - 搜索股票代码 → 点击「Valuation」页签
              - 点击「Grade & Metrics」页签
              - 查看「P/E Non-GAAP (TTM)」指标
            """)
        
        pe_lower_adj = st.number_input("滚动PE下限", value=float(pe_stats['pe_lower']), min_value=0.0, step=0.1)
        pe_upper_adj = st.number_input("滚动PE上限", value=float(pe_stats['pe_upper']), min_value=0.0, step=0.1)
        # 使用上限和下限的平均值作为中位数
        pe_median_default = (pe_lower_adj + pe_upper_adj) / 2
        pe_median_adj = st.number_input("滚动PE中位值", value=float(pe_median_default), min_value=0.0, step=0.1, help="中位值默认为上限和下限的平均值")
        
        # 当PE上限或下限变化时，自动更新中位数
        if 'last_pe_lower' not in st.session_state or 'last_pe_upper' not in st.session_state:
            st.session_state.last_pe_lower = pe_lower_adj
            st.session_state.last_pe_upper = pe_upper_adj
        elif st.session_state.last_pe_lower != pe_lower_adj or st.session_state.last_pe_upper != pe_upper_adj:
            st.session_state.last_pe_lower = pe_lower_adj
            st.session_state.last_pe_upper = pe_upper_adj
            # 更新中位数并重新加载页面
            st.rerun()
    
    with col2:
       
        
        # 添加EPS获取说明 - 始终显示
        st.markdown("#### 📝 自定义调整EPS预测数据")
        
        # 简洁显示数据来源提示
        st.markdown("💡 **数据来源:** [Seeking Alpha](https://seekingalpha.com) (推荐) | [Yahoo Finance](https://finance.yahoo.com) | 公司财报")
        
        # 创建小型下拉框，仅在需要时展开详细说明
        with st.expander("查看详细获取方法", expanded=False):
            # 添加数据获取说明
            st.markdown("""
           
             **Seeking Alpha 前瞻EPS查询方法：** 
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
            eps_fy_current = st.number_input("当前财年 EPS", 
                                            key="eps_fy_current_input",
                                            value=forward_eps.get(fiscal_years[0]) or 0.0, 
                                            min_value=0.0, step=0.01, format="%.2f")
        else:
            eps_fy_current = st.number_input("当前财年 EPS", 
                                           key="eps_fy_current_input",
                                           value=0.0, min_value=0.0, step=0.01, format="%.2f")
            
        if len(fiscal_years) >= 2:
            eps_fy_next = st.number_input("下一财年 EPS", 
                                        key="eps_fy_next_input",
                                        value=forward_eps.get(fiscal_years[1]) or 0.0, 
                                        min_value=0.0, step=0.01, format="%.2f")
        else:
            eps_fy_next = st.number_input("下一财年 EPS", 
                                        key="eps_fy_next_input",
                                        value=0.0, min_value=0.0, step=0.01, format="%.2f")
            
        # 移除后年财年的输入框
    
    # 重新计算按钮
    if st.button("🔄 计算估值", type="primary"):
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
        
        # 估值表格
        st.subheader("📋 估值详情")
        
        # 创建DataFrame用于显示
        df_display = pd.DataFrame([]
        )
        
        # 根据结果数量创建适当的标签
        if len(valuation_results) == 1:
            fiscal_labels = ["当前财年"]
        elif len(valuation_results) == 2:
            fiscal_labels = ["当前财年", "下一财年"]
        else:
            fiscal_labels = [f"财年{i+1}" for i in range(len(valuation_results))]
        
        # 创建DataFrame用于显示，使用新的财年标签
        df_display = pd.DataFrame([
            {
                '财年': fiscal_labels[i],
                '前瞻EPS': result['eps'],
                '滚动PE区间': result['pe_range'],
                '估值范围': result['valuation_range'],
                'EPS来源': result['source']
            }
            for i, result in enumerate(valuation_results)
        ])
        
        st.dataframe(df_display, use_container_width=True)
        
        # 估值图表
        valuation_chart = create_valuation_chart(valuation_results)
        if valuation_chart:
            st.plotly_chart(valuation_chart, use_container_width=True)
        
        # 估值总结模块已移除
        


if __name__ == "__main__":
    main()