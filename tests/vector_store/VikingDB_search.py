
import json
import requests

from volcengine.auth.SignerV4 import SignerV4
from volcengine.base.Request import Request
from volcengine.Credentials import Credentials

collection_name = "ai_recruitment"
HOST = "api-knowledgebase.mlp.cn-beijing.volces.com"
ENDPOINT = "tos-cn-beijing.volces.com"
REGION = "cn-beijing"
project_name = "default"
query = "一诺前景目前有哪些岗位招人"
# image_query = "请传入可访问的图片URL或者Base64编码"
ak = "AKLTM2EwNDczYWE4OTk5NDYwNDhhNGZlNDIyOTMyYzkxZDM"
sk = "TnpjNE5Ea3dNVFkyTVdaaE5EZzRaVGs1WlRBd05UQTNOekE0WmpZeU5qTQ=="
g_knowledge_base_domain = "api-knowledgebase.mlp.cn-beijing.volces.com"
account_id = "kb-b66fc9b9a7d4c04e"


def prepare_request(method, path, params=None, data=None, doseq=0):
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
        "Host": g_knowledge_base_domain,
        "V-Account-Id": account_id,
    }
    r.set_headers(mheaders)
    if params:
        r.set_query(params)
    r.set_host(g_knowledge_base_domain)
    r.set_path(path)
    if data is not None:
        r.set_body(json.dumps(data))

    # 生成签名
    credentials = Credentials(ak, sk, "air", "cn-north-1")
    SignerV4.sign(r, credentials)
    return r


def search_knowledge(query=None, k=3, return_scores=False):
    method = "POST"
    path = "/api/knowledge/collection/search_knowledge"
    # 如果提供了query参数，使用它；否则使用默认query
    search_query = query if query else globals().get('query', "一诺前景目前有哪些岗位招人")
    request_params = {
    "project": project_name,
    "name": collection_name,
    "query": search_query,
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
    },
    # "image_query": image_query
}


    info_req = prepare_request(method=method, path=path, data=request_params)
    rsp = requests.request(
        method=info_req.method,
        url="http://{}{}".format(g_knowledge_base_domain, info_req.path),
        headers=info_req.headers,
        data=info_req.body
    )
    
    # 提取并处理结果
    try:
        json_data = rsp.json()
        
        # 检查响应结构
        if json_data.get('code') == 0 and 'data' in json_data:
            data = json_data['data']
            
            # 获取result_list（即文档片段列表）
            result_list = data.get('result_list', [])
            
            if not result_list:
                print("未找到结果列表")
                if return_scores:
                    return [], []
                return []
            
            # 按score降序排序
            sorted_results = sorted(result_list, key=lambda x: x.get('score', 0), reverse=True)
            
            # 选取前K个结果
            top_k_results = sorted_results[:k]
            
            # 打印结果
            for i, result in enumerate(top_k_results, 1):
                score = result.get('score', 0)
                content = result.get('content', '')
                doc_name = result.get('doc_info', {}).get('doc_name', '未知文档')
                
                # print(f"\n--- 结果 {i} (score: {score:.4f}) ---")
                # print(f"来源文档: {doc_name}")
                # print(f"内容: {content[:200]}..." if len(content) > 200 else f"内容: {content}")
            
            # 返回结果
            top_k_contents = [result.get('content', '') for result in top_k_results]
            top_k_scores = [result.get('score', 0) for result in top_k_results]
            
            if return_scores:
                return top_k_contents, top_k_scores
            return top_k_contents
        else:
            print("响应数据结构不符合预期")
            if return_scores:
                return [], []
            return []
            
    except Exception as e:
        print(f"处理响应失败: {e}")
        if return_scores:
            return [], []
        return []


if __name__ == "__main__":
    result = search_knowledge()
