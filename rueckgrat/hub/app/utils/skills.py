import re
import json
import os
from typing import Dict, List, Optional

from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class Skills:
    def __init__(self, directory_path: str):
        self.skills: Dict[str, str] = {}
        self._load_skills(directory_path)

    def _load_skills(self, directory_path: str) -> None:
        if not os.path.isdir(directory_path):
            logger.warning(f"directory not found - {directory_path}")
            return

        for filename in sorted(os.listdir(directory_path)):
            if not filename.endswith('.md'):
                continue

            filepath = os.path.join(directory_path, filename)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().strip()
                
                name_match = re.search(r'"tool"\s*:\s*"([^"]+)"', content)
                if name_match:
                    tool_name = name_match.group(1).strip()
                    self.skills[tool_name] = content
                else:
                    logger.warning(f"No skill name found in {filename}. Check syntax")
                    
            except Exception as e:
                logger.error(f"failed reading {filename}: {e}")
                return                    
        
        skills_list = ""
        for key, value in self.skills.items():
            skills_list += key + "\n"

        logger.debug(f"loaded skills:\n{skills_list}")

    def get_skills_text(self, skill_names: Optional[List[str]] = None) -> str:
        if not skill_names:
            selected = self.skills.values()
        else:
            selected = [self.skills[name] for name in skill_names if name in self.skills]
        
        return "\n\n".join(selected)
    
    def extract_tool_calls(self, text: str) -> tuple[List[Dict], str]:
            tool_calls = []
            cleaned_text = text
            
            json_pattern = r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}'
            matches = re.findall(json_pattern, text, re.DOTALL)
            
            for match in matches:
                try:
                    data = Utils.json_loads(match)
                    if data and "tool" in data:
                        if data["tool"] in self.skills:
                            tool_calls.append(data)
                            cleaned_text = cleaned_text.replace(match, "").strip()
                except:
                    continue
            
            return tool_calls, cleaned_text