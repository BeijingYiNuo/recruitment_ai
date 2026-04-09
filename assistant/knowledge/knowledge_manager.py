import json
import requests
from typing import List, Tuple, Optional

from volcengine.auth.SignerV4 import SignerV4
from volcengine.base.Request import Request
from volcengine.Credentials import Credentials

from assistant.utils.logger import logger
from assistant.config.config_manager import ConfigManager
class KnowledgeManager:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.collection_name = self.config_manager.config['knowledge']['collection_name']
        self.host = self.config_manager.config['knowledge']['host']
        self.region = self.config_manager.config['knowledge']['region']
        self.project_name = self.config_manager.config['knowledge']['project_name']
        self.ak = self.config_manager.config['knowledge']['ak']     #用于表示拥护知识库的访问权限
        self.sk = self.config_manager.config['knowledge']['sk']    #用于验证用户的密钥
        self.account_id = self.config_manager.config['knowledge']['account_id']
        self.knowledge_sources = []
    
    def initialize_knowledge_sources(self) -> None:
        """
        初始化知识库源
        """
        # 这里可以添加初始化逻辑
        self.knowledge_sources = ["default"]
        logger.info("Knowledge sources initialized")
    def create_knowledge(self, user_id: str, name: str, chunking_strategy: str = 'custom_balance'):
        """
        创建知识库
        
        Args:
            user_id: 用户ID
            name: 知识库名称
            description: 知识库描述
            chunking_strategy: 切片策略
            
        Returns:
            dict: 创建结果
        """
        try:
            method = "POST"
            path = "/api/knowledge/collection/create"
            request_params = {
                "name": name,
                "version": 2,
                "preprocessing": {
                    "chunking_strategy": chunking_strategy,
                    "multi_modal": ["image_ocr"]
                }
            }
            
            info_req = self._prepare_request(method=method, path=path, data=request_params)
            rsp = requests.request(
                method=info_req.method,
                url="https://{}{}".format(self.host, info_req.path),
                headers=info_req.headers,
                data=info_req.body
            )
            
            json_data = rsp.json()
            logger.info(f"user {user_id} Create knowledge response: {json_data}")
            
            return json_data
        except Exception as e:
            logger.error(f"user {user_id} Error creating knowledge: {e}")
            raise e
    def info_knowledge(self, user_id: str, name: str) -> dict:
        """
        获取知识库信息
        
        Args:
            user_id: 用户 ID
            name: 知识库名称
            
        Returns:
            dict: 知识库信息
        """
        try:
            method = "POST"
            path = "/api/knowledge/collection/info"
            request_params = {
                "name": name,
            }
            
            info_req = self._prepare_request(method=method, path=path, data=request_params)
            rsp = requests.request(
                method=info_req.method,
                url="https://{}{}".format(self.host, info_req.path),
                headers=info_req.headers,
                data=info_req.body
            )
            
            json_data = rsp.json()
            logger.info(f"user {user_id} Info knowledge response: {json_data}")
            
            return json_data
        except Exception as e:
            logger.error(f"user {user_id} Error info knowledge: {e}")
            raise e
    
    def update_knowledge(self, user_id: str, name: str, description: str) -> dict:
        """
        更新知识库
        
        Args:
            user_id: 用户 ID
            name: 知识库名称
            description: 知识库描述
            
        Returns:
            dict: 更新结果
        """
        try:
            method = "POST"
            path = "/api/knowledge/collection/update"
            request_params = {
                "name": name,
                "description": description,
            }
            
            info_req = self._prepare_request(method=method, path=path, data=request_params)
            rsp = requests.request(
                method=info_req.method,
                url="https://{}{}".format(self.host, info_req.path),
                headers=info_req.headers,
                data=info_req.body
            )
            
            json_data = rsp.json()
            logger.info(f"user {user_id} Update knowledge response: {json_data}")
            
            return json_data
        except Exception as e:
            logger.error(f"user {user_id} Error updating knowledge: {e}")
            raise e
    
    def delete_knowledge(self, user_id: str, name: str) -> dict:
        """
        删除知识库
        
        Args:
            user_id: 用户 ID
            name: 知识库名称
            
        Returns:
            dict: 删除结果
        """
        try:
            method = "POST"
            path = "/api/knowledge/collection/delete"
            request_params = {
                "name": name,
            }
            
            info_req = self._prepare_request(method=method, path=path, data=request_params)
            rsp = requests.request(
                method=info_req.method,
                url="https://{}{}".format(self.host, info_req.path),
                headers=info_req.headers,
                data=info_req.body
            )
            
            json_data = rsp.json()
            logger.info(f"user {user_id} Delete knowledge response: {json_data}")
            
            return json_data
        except Exception as e:
            logger.error(f"user {user_id} Error deleting knowledge: {e}")
            raise e
    
    def add_knowledge_source(self, source: str) -> None:
        """
        添加知识库源
        
        Args:
            source: 知识库源
        """
    
    def remove_knowledge_source(self, source: str) -> None:
        """
        移除知识库源
        
        Args:
            source: 知识库源
        """
        
    
    def get_knowledge_sources(self) -> List[str]:
        """
        获取知识库源列表
        
        Returns:
            List[str]: 知识库源列表
        """
       
    
    def get_knowledge_trigger(self, user_id: str, client: Optional[object] = None) -> 'KnowledgeTrigger':
        """
        获取知识库触发器
        
        Args:
            user_id: 用户ID
            client: LLM客户端
            
        Returns:
            KnowledgeTrigger: 知识库触发器
        """
        return KnowledgeTrigger(shared_client=client)
    
    def _search_knowledge(self, query: str, k: int = 3, return_scores: bool = False) -> List[str] or Tuple[List[str], List[float]]:
        """
        搜索知识库
        
        Args:
            query: 查询内容
            k: 返回结果数量
            return_scores: 是否返回分数
            
        Returns:
            List[str] or Tuple[List[str], List[float]]: 搜索结果
        """
        method = "POST"
        path = "/api/knowledge/collection/search_knowledge"
        request_params = {
        "project": self.project_name,
        "name": self.collection_name,
        "query": query,
        "limit": 10,
        "pre_processing": {
            "need_instruction": True,
            "return_token_usage": True,
            "messages": [
                {
                    "role": "system",
                    "content": ""
                },
                {
                    "role": "user"
                }
            ]
        },
        "dense_weight": 0.5,
        "post_processing": {
            "get_attachment_link": True,
            "rerank_only_chunk": False,
            "rerank_switch": False
        }
        }

        info_req = self._prepare_request(method=method, path=path, data=request_params)
        rsp = requests.request(
            method=info_req.method,
            url="http://{}{}".format(self.host, info_req.path),
            headers=info_req.headers,
            data=info_req.body
        )
        
        try:
            json_data = rsp.json()
            
            if json_data.get('code') == 0 and 'data' in json_data:
                data = json_data['data']
                result_list = data.get('result_list', [])
                
                if not result_list:
                    if return_scores:
                        return [], []
                    return []
                
                sorted_results = sorted(result_list, key=lambda x: x.get('score', 0), reverse=True)
                top_k_results = sorted_results[:k]
                
                top_k_contents = [result.get('content', '') for result in top_k_results]
                top_k_scores = [result.get('score', 0) for result in top_k_results]
                
                if return_scores:
                    return top_k_contents, top_k_scores
                return top_k_contents
            else:
                if return_scores:
                    return [], []
                return []
                
        except Exception as e:
            logger.error(f"Error processing knowledge search response: {e}")
            if return_scores:
                return [], []
            return []
    
    def _prepare_request(self, method, path, params=None, data=None, doseq=0):
        """
        准备请求
        
        Args:
            method: 请求方法
            path: 请求路径
            params: 请求参数
            data: 请求数据
            doseq: 是否序列化列表
            
        Returns:
            Request: 请求对象
        """
        if params:
            for key in params:
                if (
                        isinstance(params[key], int)
                        or isinstance(params[key], float)
                        or isinstance(params[key], bool)
                ):
                    params[key] = str(params[key])
                elif isinstance(params[key], list):
                    if not doseq:
                        params[key] = ",".join(params[key])
        r = Request()
        r.set_shema("http")
        r.set_method(method)
        r.set_connection_timeout(10)
        r.set_socket_timeout(10)
        mheaders = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Host": self.host,
            "V-Account-Id": self.account_id,
        }
        r.set_headers(mheaders)
        if params:
            r.set_query(params)
        r.set_host(self.host)
        r.set_path(path)
        if data is not None:
            r.set_body(json.dumps(data))

        credentials = Credentials(self.ak, self.sk, "air", "cn-north-1")
        SignerV4.sign(r, credentials)
        return r

class KnowledgeTrigger:
    """
    知识库检索触发判断器
    采用混合策略判断是否需要触发知识库检索
    """
    
    def __init__(self, shared_client: Optional[object] = None):
        # 第一层：关键词快速触发规则
        self.MUST_SEARCH_KEYWORDS = [
            # 公司岗位信息
            "岗位", "招聘", "职位", "工作", "薪资", "福利", "待遇", "入职", "简历",
            # 制度流程
            "制度", "流程", "规定", "政策", "办法", "方案", "流程", "步骤", "要求",
            # 产品参数
            "产品", "参数", "功能", "特性", "规格", "型号", "价格", "报价",
            # 文档内容
            "文档", "资料", "文件", "内容", "信息", "数据", "详情", "说明"
        ]
        self.llm_trigger = shared_client
        
        # 第二层：轻量检索阈值设置
        self.HIGH_THRESHOLD = 0.8  # 高于此分数直接触发
        self.LOW_THRESHOLD = 0.6   # 低于此分数不触发
        # 分数在[LOW_THRESHOLD, HIGH_THRESHOLD]之间时触发第三层
        
        # 第三层：LLM分类提示词
        self.LLM_PROMPT = "你是一个知识库检索触发判断器，判断用户的问题是否需要检索知识库。如果需要，回复'需要'，否则回复'不需要'。"
    
    def hybrid_trigger(self, block_text):
        """
        混合策略触发函数
        按照三层策略顺序执行，决定是否触发知识库检索
        
        Args:
            block_text: 文本块
            
        Returns:
            bool: 是否需要检索知识库
        """
        logger.info(f"=== 开始混合策略触发判断 ===")
        
        # 第一层：关键词快速触发
        if self.rule_search(block_text):
            logger.info("=== 关键词触发 需要检索知识库 ===")
            return True
        # 第二层：轻量检索
        # 这里简化处理，直接返回False
        return False
    
    def rule_search(self, block_text):
        """
        第一层：关键词快速触发
        对必须查知识库的问题直接触发
        
        Args:
            block_text: 文本块
            
        Returns:
            bool: 是否触发
        """
        block_text_lower = block_text.lower()
        for keyword in self.MUST_SEARCH_KEYWORDS:
            if keyword in block_text_lower:
                return True
        return False
