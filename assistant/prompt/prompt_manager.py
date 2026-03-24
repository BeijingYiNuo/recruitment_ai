from typing import Dict, Any
import os

class PromptManager:
    def __init__(self):
        self.templates: Dict[str, str] = {}
        self._load_templates()
    
    def _load_templates(self):
        """
        从文件中加载提示词模板
        """
        prompt_dir = os.path.dirname(__file__)
        
        # 加载segment_judge模板
        segment_judge_path = os.path.join(prompt_dir, 'segment_judge.txt')
        if os.path.exists(segment_judge_path):
            with open(segment_judge_path, 'r', encoding='utf-8') as f:
                self.templates['segment_judge'] = f.read()
        
        # 加载analysis模板
        analysis_path = os.path.join(prompt_dir, 'analysis.txt')
        if os.path.exists(analysis_path):
            with open(analysis_path, 'r', encoding='utf-8') as f:
                self.templates['analysis'] = f.read()
        
        # 加载knowledge_trigger模板
        knowledge_trigger_path = os.path.join(prompt_dir, 'knowledge_trigger.txt')
        if os.path.exists(knowledge_trigger_path):
            with open(knowledge_trigger_path, 'r', encoding='utf-8') as f:
                self.templates['knowledge_trigger'] = f.read()
    
    def get_prompt_template(self, template_name: str) -> str:
        """
        获取提示词模板
        
        Args:
            template_name: 模板名称
            
        Returns:
            str: 提示词模板
        """
        return self.templates.get(template_name, "")
    
    def generate_prompt(self, user_id: str, template_name: str, **kwargs) -> str:
        """
        生成提示词
        
        Args:
            user_id: 用户ID
            template_name: 模板名称
            **kwargs: 模板参数
            
        Returns:
            str: 生成的提示词
        """
        template = self.get_prompt_template(template_name)
        if not template:
            return ""
        
        try:
            return template.format(**kwargs)
        except KeyError:
            return template
    
    def add_prompt_template(self, template_name: str, template: str) -> None:
        """
        添加提示词模板
        
        Args:
            template_name: 模板名称
            template: 模板内容
        """
        self.templates[template_name] = template
    
    def remove_prompt_template(self, template_name: str) -> None:
        """
        移除提示词模板
        
        Args:
            template_name: 模板名称
        """
        if template_name in self.templates:
            del self.templates[template_name]
    
    def list_prompt_templates(self) -> list:
        """
        列出所有提示词模板
        
        Returns:
            list: 模板名称列表
        """
        return list(self.templates.keys())
