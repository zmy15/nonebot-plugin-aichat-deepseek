"""长期记忆工具共享的分类和长度限制。"""

MEMORY_CATEGORIES = (
    "profile",
    "preference",
    "habit",
    "relationship",
    "fact",
)
MEMORY_CATEGORY_LABELS = {
    "profile": "个人信息",
    "preference": "偏好",
    "habit": "习惯",
    "relationship": "关系",
    "fact": "事实",
}
MAX_MEMORY_CHARS = 500
