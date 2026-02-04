#下面示例通过SDK创建知识库、上传文档和检索查询的完整流程

#创建知识库
from volcengine.viking_knowledgebase import VikingKnowledgeBaseService, Collection, Doc, Point
from volcengine.viking_knowledgebase.common import Field, FieldType, IndexType, EmbddingModelType, CollectionVersion


AK = "AKLTM2EwNDczYWE4OTk5NDYwNDhhNGZlNDIyOTMyYzkxZDM"
SK = "TnpjNE5Ea3dNVFkyTVdaaE5EZzRaVGs1WlRBd05UQTNOekE0WmpZeU5qTQ=="
HOST = "api-knowledgebase.mlp.cn-beijing.volces.com"
ENDPOINT = "tos-cn-beijing.volces.com"
REGION = "cn-beijing"
viking_knowledgebase_service = VikingKnowledgeBaseService(host=HOST, scheme="https", connection_timeout=30, socket_timeout=30)
viking_knowledgebase_service.set_ak(AK)
viking_knowledgebase_service.set_sk(SK)
collection_name = "ai_recruitment"
description = "存储销售行业话术、企业文化发展、企业实时知识相关的数据文档"

# 检查集合是否存在，如果存在就删除它
print(f"Checking if collection '{collection_name}' exists...")
index = {
   "index_type": IndexType.HNSW_HYBRID,
   "index_config": {
        "fields": [{
            "field_name": "chunk_len",
            "field_type": FieldType.Int64,
            "default_val": 0
            }],
        "cpu_quota": 1,
        "embedding_model":EmbddingModelType.EmbeddingModelBgeLargeZhAndM3
  }
}
preprocessing = {
    "chunk_length" : 200
}
try:
    # 尝试获取集合信息
    collections = viking_knowledgebase_service.list_collections()
    for coll in collections:
        if coll.collection_name == collection_name:
            my_collection = coll
            print(f"Collection '{collection_name}' exists, using it...")
            continue
        else:
            my_collection = viking_knowledgebase_service.create_collection(
            collection_name=collection_name, 
            version=CollectionVersion.UltimateVersion,
            description=description,
            index=index,
            preprocessing=preprocessing)
            print(f"Collection '{collection_name}' created successfully!")

except Exception as e:
    print(f"Error checking/dropping collection: {e}")


# 等待集合完全注册到系统中
import time
print("Waiting for collection to be fully registered...")
collection_exists = False
max_attempts = 10
for i in range(max_attempts):
    try:
        # 尝试获取集合信息
        collection_info = viking_knowledgebase_service.get_collection(collection_name)
        print(f"Collection '{collection_name}' is now available!")
        collection_exists = True
        break
    except Exception as e:
        print(f"Attempt {i+1}/{max_attempts}: Collection not available yet: {e}")
        time.sleep(3)  # 等待3秒后重试

if not collection_exists:
    print(f"Error: Collection '{collection_name}' could not be created or is not available after {max_attempts} attempts")
    exit(1)

import tos
import time

# 使用唯一的bucket名称，避免命名冲突
timestamp = int(time.time())
bucket_name = f"ai-recruitment-{timestamp}"  # 替换为你的 bucket 名称
object_key = "documents/yinuo.txt"  # 替换为你想在 TOS 中保存的路径
local_file = "/Users/xuhaoran/Documents/trae_projects/interview-assistant/data/yinuo.txt"
tos_path = f"tos://{bucket_name}/{object_key}"
try:
    tos_client = tos.TosClientV2(ak=AK, sk=SK, endpoint=ENDPOINT, region=REGION)
    buckets = tos_client.list_buckets()
    buckets_names = [b.name for b in buckets.buckets]
    
    print(f"Found {len(buckets_names)} buckets:")
    for bucket in buckets_names:
        print(f"- {bucket}")
    
    # 删除所有现有的bucket
    for bucket in buckets_names:
        print(f"\nProcessing bucket: {bucket}")
        # 列出并删除bucket中的所有对象
        try:
            objects = tos_client.list_objects(bucket=bucket)
            if hasattr(objects, 'contents') and objects.contents:
                print(f"Found {len(objects.contents)} objects in bucket {bucket}:")
                for obj in objects.contents:
                    tos_client.delete_object(bucket=bucket, key=obj.key)
                    print(f"Deleted object: {obj.key}")
            else:
                print(f"No objects found in bucket {bucket}")
        except Exception as e:
            print(f"Error listing objects: {e}")
        
        # 删除bucket
        tos_client.delete_bucket(bucket=bucket)
        print(f"Deleted bucket: {bucket}")

    print("\nAll buckets deleted successfully!")
    
    # 验证所有bucket已被删除
    buckets_after_delete = tos_client.list_buckets()
    buckets_after_delete_names = [b.name for b in buckets_after_delete.buckets]
    print(f"After deletion, found {len(buckets_after_delete_names)} buckets:")
    for bucket in buckets_after_delete_names:
        print(f"- {bucket}")
    
    # 创建新的bucket
    result = tos_client.create_bucket(bucket=bucket_name)
    print(f"\nBucket '{bucket_name}' created successfully!")
    
    # 上传文件
    tos_client.upload_file(bucket=bucket_name, key=object_key, file_path=local_file)
    print(f"File '{local_file}' uploaded to '{bucket_name}/{object_key}' successfully!")
    
    
    

except Exception as e:
    print(f"Error creating TosClientV2: {e}")
    exit(1)

