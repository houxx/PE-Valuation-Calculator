import os
import json
import pickle
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, Any, Optional
import hashlib

class CacheManager:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        self.ensure_cache_dir()
        
        # 缓存过期时间设置
        self.cache_expiry = {
            'stock_price': timedelta(days=1),      # 股价数据：1天
            'eps_data': timedelta(weeks=1),        # EPS数据：1周
            'calculated_results': timedelta(days=1) # 计算结果：1天
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
    
    def load_cache(self, ticker: str, data_type: str, **kwargs) -> Optional[tuple]:
        """从缓存加载数据"""
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
        if self._is_cache_expired(data_type, created_at):
            return None
        
        # 更新最后访问时间
        metadata['last_accessed'] = datetime.now().isoformat()
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
        
        expiry_time = self.cache_expiry[data_type]
        return datetime.now() - created_at > expiry_time
    
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
        """清理过期和长期未使用的缓存"""
        cleanup_stats = {
            'expired_removed': 0,
            'unused_removed': 0,
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
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    created_at = datetime.fromisoformat(metadata['created_at'])
                    last_accessed = datetime.fromisoformat(metadata['last_accessed'])
                    data_type = metadata.get('data_type', 'unknown')
                    
                    # 检查是否过期
                    if self._is_cache_expired(data_type, created_at):
                        self._remove_cache_files(cache_path, meta_path)
                        cleanup_stats['expired_removed'] += 1
                        continue
                    
                    # 检查是否长期未使用
                    if datetime.now() - last_accessed > self.unused_expiry:
                        self._remove_cache_files(cache_path, meta_path)
                        cleanup_stats['unused_removed'] += 1
                        continue
                        
                except Exception as e:
                    # 如果元数据文件损坏，删除相关文件
                    self._remove_cache_files(cache_path, meta_path)
                    cleanup_stats['expired_removed'] += 1
        
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
    
    def get_data_update_time(self, ticker: str, data_type: str, **kwargs) -> Optional[str]:
        """获取数据更新时间"""
        cache_key = self._get_cache_key(ticker, data_type, **kwargs)
        meta_path = self._get_metadata_path(cache_key)
        
        if not os.path.exists(meta_path):
            return None
        
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            created_at = datetime.fromisoformat(metadata['created_at'])
            return created_at.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return self.get_cache_info()
        
    def cleanup_cache(self) -> int:
        """清理过期缓存，返回清理的文件数量"""
        cleanup_stats = self.cleanup_old_cache()
        return cleanup_stats['expired_removed'] + cleanup_stats['unused_removed']
    
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