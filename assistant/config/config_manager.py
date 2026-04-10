import json
import os
from typing import Dict, Any

class ConfigManager:
    def __init__(self):
        self.config: Dict[str, Any] = {
            'asr': {
                'url': 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async',
                'seg_duration': 200,
                'app_key': '5732215494',
                'access_key': '1nb4wqYUAauPuMABBnwi--o271GrwG43'
            },
            'llm': {
                'url': 'https://ark.cn-beijing.volces.com/api/v3/',
                'api_key': '76a878dc-4905-44c3-858c-8ef33006250f',
                'model': 'doubao-seed-1-6-251015'
            },
            'knowledge': {
                'collection_name': 'ai_recruitment',
                'host': 'api-knowledgebase.mlp.cn-beijing.volces.com',
                'region': 'cn-beijing',
                'project_name': 'default',
                'ak': 'AKLTM2EwNDczYWE4OTk5NDYwNDhhNGZlNDIyOTMyYzkxZDM',
                'sk':'TnpjNE5Ea3dNVFkyTVdaaE5EZzRaVGs1WlRBd05UQTNOekE0WmpZeU5qTQ==',
                'account_id': 'kb-b66fc9b9a7d4c04e'
            },
            'knowledge_default': {
                'role': 'USER',
                'project': 'default',
                'version': 2,
                'chunking_strategy': 'custom_balance',
                'chunk_length': 500,
                'merge_small_chunks': True,
                'enabled': False
            },
            'tos':{
                'access_key':'AKLTM2EwNDczYWE4OTk5NDYwNDhhNGZlNDIyOTMyYzkxZDM',
                'secret_key':'TnpjNE5Ea3dNVFkyTVdaaE5EZzRaVGs1WlRBd05UQTNOekE0WmpZeU5qTQ==',
                'region':'cn-beijing',
                'endpoint':'tos-cn-beijing.volces.com',
                'bucket_name':'ai-recruitment-beijing'
            }
        }
    
    def load_config(self, config_file: str) -> None:
        """
        加载配置文件
        
        Args:
            config_file: 配置文件路径
        """
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                self.config.update(loaded_config)
    
    def get_asr_config(self) -> Dict[str, Any]:
        """
        获取ASR配置
        
        Returns:
            Dict[str, Any]: ASR配置
        """
        return self.config.get('asr', {})
    
    def get_llm_config(self) -> Dict[str, Any]:
        """
        获取LLM配置
        
        Returns:
            Dict[str, Any]: LLM配置
        """
        return self.config.get('llm', {})
    
    def get_knowledge_config(self) -> Dict[str, Any]:
        """
        获取知识库配置
        
        Returns:
            Dict[str, Any]: 知识库配置
        """
        return self.config.get('knowledge', {})
    
    def get_knowledge_default_config(self) -> Dict[str, Any]:
        """
        获取知识库默认配置
        
        Returns:
            Dict[str, Any]: 知识库默认配置
        """
        return self.config.get('knowledge_default', {})
    
    def update_config(self, section: str, key: str, value: Any) -> None:
        """
        更新配置
        
        Args:
            section: 配置 section
            key: 配置 key
            value: 配置 value
        """
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value