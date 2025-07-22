import os
import json
import pickle
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, Any, Optional
import hashlib
import pytz

class CacheManager:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        self.ensure_cache_dir()
        
        # 美东时区
        self.et_tz = pytz.timezone('US/Eastern')
        
        # 缓存过期时间设置 - 基于交易日
        self.cache_expiry = {
            'stock_data': 'trading_day',           # 股价数据：交易日更新
            'stock_info': 'trading_day',           # 股票信息：交易日更新
            'eps_ttm': timedelta(weeks=1),         # TTM EPS：1周
            'forward_eps': timedelta(weeks=1),     # 前瞻EPS：1周
            'calculated_results': 'trading_day'    # 计算结果：交易日更新
        }
        
        # 数据未使用超过3个月自动删除
        self.unused_expiry = timedelta(days=90)
    
    def ensure_cache_dir(self):
        """确保缓存目录存在"""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
    def _get_cache_key(self, ticker: str, data_type: str, **kwargs) -> str:
        """生成缓存键"""
        key_data = f"{ticker}_{data_type}"
        if kwargs:
            key_data += "_" + "_".join([f"{k}_{v}" for k, v in sorted(kwargs.items())])
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")
    
    def _get_metadata_path(self, cache_key: str) -> str:
        """获取元数据文件路径"""
        return os.path.join(self.cache_dir, f"{cache_key}_meta.json")
    
    def save_cache(self, ticker: str, data_type: str, data: Any, **kwargs) -> str:
        """保存数据到缓存"""
        cache_key = self._get_cache_key(ticker, data_type, **kwargs)
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_metadata_path(cache_key)
        
        # 保存数据
        with open(cache_path, 'wb') as f:
            pickle.dump(data, f)
        
        # 保存元数据
        metadata = {
            'ticker': ticker,
            'data_type': data_type,
            'created_at': datetime.now().isoformat(),
            'last_accessed': datetime.now().isoformat(),
            'kwargs': kwargs
        }
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return cache_key
    
    def load_cache(self, ticker: str, data_type: str, allow_expired: bool = False, **kwargs) -> Optional[tuple]:
        """从缓存加载数据，支持过期检查和强制使用过期数据"""
        cache_key = self._get_cache_key(ticker, data_type, **kwargs)
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_metadata_path(cache_key)
        
        if not os.path.exists(cache_path) or not os.path.exists(meta_path):
            return None
        
        # 读取元数据
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except:
            return None
        
        # 检查缓存是否过期
        created_at = datetime.fromisoformat(metadata['created_at'])
        is_expired = self._is_cache_expired(data_type, created_at)
        
        # 如果过期且不允许使用过期数据，返回None
        if is_expired and not allow_expired:
            return None
        
        # 更新最后访问时间
        metadata['last_accessed'] = datetime.now().isoformat()
        metadata['is_expired'] = is_expired
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # 读取数据
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            return data, metadata
        except:
            return None
    
    def _is_cache_expired(self, data_type: str, created_at: datetime) -> bool:
        """检查缓存是否过期"""
        if data_type not in self.cache_expiry:
            return True
        
        expiry_rule = self.cache_expiry[data_type]
        
        # 如果是交易日规则
        if expiry_rule == 'trading_day':
            return self._is_trading_day_expired(created_at)
        
        # 如果是时间间隔规则
        if isinstance(expiry_rule, timedelta):
            return datetime.now() - created_at > expiry_rule
        
        return True
    
    def _is_trading_day_expired(self, created_at: datetime) -> bool:
        """检查基于交易日的缓存是否过期"""
        # 获取当前美东时间
        now_et = datetime.now(self.et_tz)
        created_at_et = created_at.replace(tzinfo=pytz.UTC).astimezone(self.et_tz)
        
        # 获取最近的交易日收盘时间（美东时间下午4点）
        last_trading_close = self._get_last_trading_close(now_et)
        
        # 如果缓存创建时间早于最近的交易日收盘时间，则过期
        return created_at_et < last_trading_close
    
    def _get_last_trading_close(self, current_time_et: datetime) -> datetime:
        """获取最近的交易日收盘时间（美东时间下午4点）"""
        # 美股交易时间：周一到周五，美东时间9:30-16:00
        current_date = current_time_et.date()
        
        # 如果是周末，回退到上周五
        while current_date.weekday() >= 5:  # 5=周六, 6=周日
            current_date -= timedelta(days=1)
        
        # 设置收盘时间为下午4点
        close_time = datetime.combine(current_date, datetime.min.time().replace(hour=16))
        close_time_et = self.et_tz.localize(close_time)
        
        # 如果当前时间是交易日但还没到收盘时间，使用前一个交易日的收盘时间
        if current_time_et.date() == current_date and current_time_et.time() < datetime.min.time().replace(hour=16):
            # 回退到前一个交易日
            prev_date = current_date - timedelta(days=1)
            while prev_date.weekday() >= 5:
                prev_date -= timedelta(days=1)
            close_time = datetime.combine(prev_date, datetime.min.time().replace(hour=16))
            close_time_et = self.et_tz.localize(close_time)
        
        return close_time_et
    
    def force_refresh_cache(self, ticker: str, data_type: str, **kwargs) -> bool:
        """强制刷新缓存（删除现有缓存）"""
        cache_key = self._get_cache_key(ticker, data_type, **kwargs)
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_metadata_path(cache_key)
        
        deleted = False
        if os.path.exists(cache_path):
            os.remove(cache_path)
            deleted = True
        
        if os.path.exists(meta_path):
            os.remove(meta_path)
            deleted = True
        
        return deleted
    
    def cleanup_old_cache(self) -> Dict[str, int]:
        """手动清理缓存（已移除自动过期检查）"""
        cleanup_stats = {
            'manually_removed': 0,
            'total_files': 0
        }
        
        if not os.path.exists(self.cache_dir):
            return cleanup_stats
        
        for filename in os.listdir(self.cache_dir):
            if filename.endswith('_meta.json'):
                meta_path = os.path.join(self.cache_dir, filename)
                cache_key = filename.replace('_meta.json', '')
                cache_path = self._get_cache_path(cache_key)
                
                cleanup_stats['total_files'] += 1
                
                try:
                    # 只处理元数据文件损坏的情况
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                except Exception as e:
                    # 如果元数据文件损坏，删除相关文件
                    self._remove_cache_files(cache_path, meta_path)
                    cleanup_stats['manually_removed'] += 1
        
        return cleanup_stats
    
    def _remove_cache_files(self, cache_path: str, meta_path: str):
        """删除缓存文件和元数据文件"""
        if os.path.exists(cache_path):
            os.remove(cache_path)
        if os.path.exists(meta_path):
            os.remove(meta_path)
    
    def get_cache_info(self, ticker: str = None) -> Dict[str, Any]:
        """获取缓存信息"""
        cache_info = {
            'total_files': 0,
            'total_size_mb': 0,
            'by_ticker': {},
            'by_data_type': {},
            'oldest_cache': None,
            'newest_cache': None
        }
        
        if not os.path.exists(self.cache_dir):
            return cache_info
        
        oldest_time = None
        newest_time = None
        
        for filename in os.listdir(self.cache_dir):
            if filename.endswith('_meta.json'):
                meta_path = os.path.join(self.cache_dir, filename)
                cache_key = filename.replace('_meta.json', '')
                cache_path = self._get_cache_path(cache_key)
                
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    ticker_name = metadata.get('ticker', 'unknown')
                    data_type = metadata.get('data_type', 'unknown')
                    created_at = datetime.fromisoformat(metadata['created_at'])
                    
                    # 如果指定了ticker，只统计该ticker的信息
                    if ticker and ticker_name.upper() != ticker.upper():
                        continue
                    
                    cache_info['total_files'] += 1
                    
                    # 计算文件大小
                    if os.path.exists(cache_path):
                        size = os.path.getsize(cache_path) / (1024 * 1024)  # MB
                        cache_info['total_size_mb'] += size
                    
                    # 按ticker统计
                    if ticker_name not in cache_info['by_ticker']:
                        cache_info['by_ticker'][ticker_name] = 0
                    cache_info['by_ticker'][ticker_name] += 1
                    
                    # 按数据类型统计
                    if data_type not in cache_info['by_data_type']:
                        cache_info['by_data_type'][data_type] = 0
                    cache_info['by_data_type'][data_type] += 1
                    
                    # 记录最新和最旧的缓存时间
                    if oldest_time is None or created_at < oldest_time:
                        oldest_time = created_at
                        cache_info['oldest_cache'] = created_at.strftime('%Y-%m-%d %H:%M:%S')
                    
                    if newest_time is None or created_at > newest_time:
                        newest_time = created_at
                        cache_info['newest_cache'] = created_at.strftime('%Y-%m-%d %H:%M:%S')
                        
                except Exception:
                    continue
        
        cache_info['total_size_mb'] = round(cache_info['total_size_mb'], 2)
        return cache_info
    
    def get_data_update_time(self, ticker: str, data_type: str, **kwargs) -> Optional[Dict[str, str]]:
        """获取数据更新时间和状态"""
        cache_key = self._get_cache_key(ticker, data_type, **kwargs)
        meta_path = self._get_metadata_path(cache_key)
        
        if not os.path.exists(meta_path):
            return None
        
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            created_at = datetime.fromisoformat(metadata['created_at'])
            is_expired = self._is_cache_expired(data_type, created_at)
            
            return {
                'update_time': created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'is_expired': is_expired,
                'status': '已过期' if is_expired else '最新'
            }
        except:
            return None
    
    def get_cache_status_summary(self, ticker: str) -> Dict[str, Any]:
        """获取指定股票的缓存状态摘要"""
        data_types = ['stock_data', 'stock_info', 'eps_ttm', 'forward_eps']
        status_summary = {
            'ticker': ticker,
            'overall_status': 'fresh',  # fresh, partial, expired, missing
            'data_status': {},
            'last_update': None,
            'expired_count': 0,
            'total_count': 0
        }
        
        latest_update = None
        
        for data_type in data_types:
            status_info = self.get_data_update_time(ticker, data_type)
            status_summary['total_count'] += 1
            
            if status_info:
                status_summary['data_status'][data_type] = status_info
                if status_info['is_expired']:
                    status_summary['expired_count'] += 1
                
                # 记录最新的更新时间
                update_time = datetime.strptime(status_info['update_time'], '%Y-%m-%d %H:%M:%S')
                if latest_update is None or update_time > latest_update:
                    latest_update = update_time
            else:
                status_summary['data_status'][data_type] = {
                    'update_time': None,
                    'is_expired': True,
                    'status': '缺失'
                }
                status_summary['expired_count'] += 1
        
        # 设置最后更新时间
        if latest_update:
            status_summary['last_update'] = latest_update.strftime('%Y-%m-%d %H:%M:%S')
        
        # 确定整体状态
        if status_summary['expired_count'] == 0:
            status_summary['overall_status'] = 'fresh'
        elif status_summary['expired_count'] == status_summary['total_count']:
            status_summary['overall_status'] = 'expired'
        else:
            status_summary['overall_status'] = 'partial'
        
        return status_summary
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return self.get_cache_info()
        
    def cleanup_cache(self) -> int:
        """手动清理缓存，返回清理的文件数量"""
        cleanup_stats = self.cleanup_old_cache()
        return cleanup_stats['manually_removed']
    
    def clear_all_cache(self) -> int:
        """清理所有缓存文件，返回清理的文件数量"""
        if not os.path.exists(self.cache_dir):
            return 0
            
        removed_count = 0
        for filename in os.listdir(self.cache_dir):
            file_path = os.path.join(self.cache_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                removed_count += 1
                
        return removed_count