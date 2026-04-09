from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from assistant.config.database import get_db
from assistant.config.config_manager import ConfigManager
from assistant.entity import User, UserKnowledge, KnowledgeRole, ChunkingStrategy
from assistant.entity.DTO import CreateKnowledgeBaseRequest
from assistant.entity.VO import KnowledgeBaseResponse
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.utils.logger import logger
from assistant.knowledge.knowledge_manager import KnowledgeManager

# 初始化配置管理器
config_manager = ConfigManager()
# 初始化知识库管理器
knowledge_manager = KnowledgeManager()

router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])


@router.post("/collection/create", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    request: CreateKnowledgeBaseRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    创建知识库
    
    - **name**: 知识库名称，不能为空，长度要求：[1-128]，知识库名称不能重复
    - **description**: 知识库描述信息，不能为空
    """
    db_user = db.query(User).filter(User.id == current_user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    # 检查知识库名称是否已存在
    existing_name = db.query(UserKnowledge).filter(UserKnowledge.name == request.name).first()
    if existing_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="知识库名称已存在"
        )
    
    # 获取默认配置
    default_config = config_manager.get_knowledge_default_config()
    
    # 创建知识库
    # 转换chunking_strategy为枚举类型
    chunking_strategy_value = default_config.get('chunking_strategy', 'custom_balance')
    if chunking_strategy_value == 'custom_balance':
        chunking_strategy_enum = ChunkingStrategy.CUSTOM_BALANCE
    else:
        chunking_strategy_enum = ChunkingStrategy.CUSTOM
    
    # 转换role为枚举类型
    role_value = default_config.get('role', 'USER')
    if role_value == 'ENTERPRISE':
        role_enum = KnowledgeRole.ENTERPRISE
    elif role_value == 'PROFESSIONAL':
        role_enum = KnowledgeRole.PROFESSIONAL
    else:
        role_enum = KnowledgeRole.USER
    
    knowledge_base = UserKnowledge(
        name=request.name,
        description=request.description,
        user_id=current_user_id,
        role=role_enum,
        project=default_config.get('project', 'default'),
        version=default_config.get('version', 2),
        chunking_strategy=chunking_strategy_enum,
        chunking_identifier=None,
        chunk_length=default_config.get('chunk_length', 500),
        merge_small_chunks=default_config.get('merge_small_chunks', True),
        enabled=default_config.get('enabled', False),
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    try:
        # 先调用API创建知识库
        api_response = knowledge_manager.create_knowledge(
            user_id=str(current_user_id),
            name=request.name,
            chunking_strategy=default_config.get('chunking_strategy', 'custom_balance')
        )
        
        # 检查API响应是否成功
        if api_response.get('code') != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"创建知识库API调用失败: {api_response.get('message', 'Unknown error')}"
            )
        # API调用成功后，将数据写入数据库
        db.add(knowledge_base)
        db.commit()
        db.refresh(knowledge_base)
        logger.info(f"User {current_user_id} created knowledge base {knowledge_base.name}")
    except Exception as e:
        db.rollback()
        logger.error(f"user {current_user_id} Error creating knowledge base: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建知识库失败"
        )
    
    # 转换响应
    response = KnowledgeBaseResponse(
        id=knowledge_base.id,
        name=knowledge_base.name,
        description=knowledge_base.description,
        user_id=knowledge_base.user_id,
        role=knowledge_base.role.value,
        project=knowledge_base.project,
        version=knowledge_base.version,
        chunking_strategy=knowledge_base.chunking_strategy.value,
        chunking_identifier=knowledge_base.chunking_identifier,
        chunk_length=knowledge_base.chunk_length,
        merge_small_chunks=knowledge_base.merge_small_chunks,
        enabled=knowledge_base.enabled,
        created_at=knowledge_base.created_at.isoformat(),
        updated_at=knowledge_base.updated_at.isoformat()
    )
    
    return response

@router.put("/collection/update", response_model=KnowledgeBaseResponse)
async def update_knowledge_info(
    description: str,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    更新知识库信息
    
    - **description**: 知识库描述信息，不能为空
    """
    db_user = db.query(User).filter(User.id == current_user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查知识库是否存在
    knowledge_base = db.query(UserKnowledge).filter(UserKnowledge.user_id == current_user_id).first()
    if not knowledge_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )
    
    try:
        # 调用 API 更新知识库
        api_response = knowledge_manager.update_knowledge(
            user_id=str(current_user_id),
            name=knowledge_base.name,
            description=description
        )
        
        # 检查 API 响应是否成功
        if api_response.get('code') != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"更新知识库 API 调用失败：{api_response.get('message', 'Unknown error')}"
            )
        
        # 更新数据库中的信息
        knowledge_base.description = description
        knowledge_base.updated_at = datetime.now()
        
        db.commit()
        db.refresh(knowledge_base)
        logger.info(f"User {current_user_id} updated knowledge base {knowledge_base.name}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"User {current_user_id} Error updating knowledge base: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新知识库失败"
        )
    
    # 转换响应
    response = KnowledgeBaseResponse(
        id=knowledge_base.id,
        name=knowledge_base.name,
        description=knowledge_base.description,
        user_id=knowledge_base.user_id,
        role=knowledge_base.role.value,
        project=knowledge_base.project,
        version=knowledge_base.version,
        chunking_strategy=knowledge_base.chunking_strategy.value,
        chunking_identifier=knowledge_base.chunking_identifier,
        chunk_length=knowledge_base.chunk_length,
        merge_small_chunks=knowledge_base.merge_small_chunks,
        enabled=knowledge_base.enabled,
        created_at=knowledge_base.created_at.isoformat(),
        updated_at=knowledge_base.updated_at.isoformat()
    )
    
    return response
    
@router.delete("/collection/delete")
async def delete_knowledge(
    name: str,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    删除知识库
    
    - **name**: 知识库名称，不能为空
    """
    db_user = db.query(User).filter(User.id == current_user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查知识库是否存在
    knowledge_base = db.query(UserKnowledge).filter(UserKnowledge.name == name).first()
    if not knowledge_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )
    
    # 验证用户权限
    if knowledge_base.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权删除该知识库"
        )
    
    try:
        # 调用 API 删除知识库
        api_response = knowledge_manager.delete_knowledge(
            user_id=str(current_user_id),
            name=name
        )
        
        # 检查 API 响应是否成功
        if api_response.get('code') != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"删除知识库 API 调用失败：{api_response.get('message', 'Unknown error')}"
            )
        
        # 从数据库中删除记录
        db.delete(knowledge_base)
        db.commit()
        logger.info(f"User {current_user_id} deleted knowledge base {name}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"User {current_user_id} Error deleting knowledge base: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除知识库失败"
        )
    
    return {
        "message": "删除成功",
        "name": name
    }


@router.get("/collection/info", response_model=KnowledgeBaseResponse)
async def get_knowledge_info(
    name: str,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    获取知识库信息
    
    - **name**: 知识库名称，不能为空
    """
    db_user = db.query(User).filter(User.id == current_user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查知识库是否存在
    knowledge_base = db.query(UserKnowledge).filter(UserKnowledge.name == name).first()
    if not knowledge_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )
    
    # 验证用户权限
    if knowledge_base.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权查看该知识库"
        )
    
    try:
        # 调用 API 获取知识库信息
        api_response = knowledge_manager.info_knowledge(
            user_id=str(current_user_id),
            name=name
        )
        
        # 检查 API 响应是否成功
        if api_response.get('code') != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取知识库信息 API 调用失败：{api_response.get('message', 'Unknown error')}"
            )
        
        # 解析 API 返回的数据
        data = api_response.get('data', {})
        
        # 从 API 响应中提取预处理配置
        preprocessing_list = data.get('preprocessing_list', [])
        preprocessing_config = preprocessing_list[0] if preprocessing_list else {}
        
        # 构建响应
        response = KnowledgeBaseResponse(
            id=knowledge_base.id,
            name=data.get('collection_name', knowledge_base.name),
            description=data.get('description', knowledge_base.description),
            user_id=knowledge_base.user_id,
            role=knowledge_base.role.value,
            project=data.get('project', knowledge_base.project),
            version=data.get('version', knowledge_base.version),
            chunking_strategy=preprocessing_config.get('chunking_strategy', knowledge_base.chunking_strategy.value),
            chunking_identifier=preprocessing_config.get('chunking_identifier'),
            chunk_length=preprocessing_config.get('chunk_length', knowledge_base.chunk_length),
            merge_small_chunks=preprocessing_config.get('merge_small_chunks', knowledge_base.merge_small_chunks),
            enabled=knowledge_base.enabled,
            created_at=knowledge_base.created_at.isoformat(),
            updated_at=knowledge_base.updated_at.isoformat()
        )
        
        logger.info(f"User {current_user_id} retrieved knowledge base info: {name}")
        return response
        
    except Exception as e:
        logger.error(f"User {current_user_id} Error retrieving knowledge base info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取知识库信息失败"
        )

