# -*- coding: utf-8 -*-
"""把 round12 的 Jev 评测语料改造成 state 为结构化对象的格式。

输入: D:/任务/jev/data/round12/jev_eval_old.jsonl
输出: D:/任务/jev/data/round15/jev_eval_old.jsonl

state 中业务数据与裁判规则分开保存：
1. task: 裁判职责和判断边界；
2. available_tools: 可选工具池；
3. conversation: 对话历史；
4. selected_tools: 当前选中工具名集合；
5. policy: 有序判断规则、特殊工具规则和高风险错误信号。
"""
import argparse
import io
import json
import os
import sys
from collections import Counter


if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


DEFAULT_TOOL_REPLY = '好的'

# ================= state 模板 =================

TASK = {
    'role': '工具选择裁判',
    'objective': '判断当前选中工具集合是否完整、准确地满足用户当前真实诉求',
    'judge_only': ['工具能力是否匹配', '明确诉求是否被完整覆盖', '是否存在更直接的候选工具'],
    'ignore': ['参数', '槽位', '参数值', '调用格式'],
    'constraints': ['结合完整对话', '只采用上下文明确支持的诉求', '禁止脑补隐含需求'],
}

POLICY = {
    'evaluation_order': [
        {
            'name': '确定当前诉求',
            'rule': (
                '判断当前输入是在补充、修正或继续上一轮，还是已明确切换到新任务；'
                '以用户当前明确要求完成的事情为准'
            ),
        },
        {
            'name': '检查诉求覆盖',
            'rule': (
                '所有明确指令都必须有对应工具；遗漏任意一项、调用无关工具，或重复执行'
                '已经完成且未被再次要求的事项，均不匹配'
            ),
        },
        {
            'name': '检查工具能力',
            'rule': (
                '仅依据 available_tools 中的描述判断；工具必须能实际完成用户最终诉求，'
                '名称相似或只能完成相关步骤均不够'
            ),
        },
        {
            'name': '比较候选工具',
            'rule': (
                '若 selected_tools 中的工具只能间接处理，而 available_tools 中有更直接、'
                '明确完成同一诉求的工具，则不匹配；不假设工具池外还有其他工具'
            ),
        },
        {
            'name': '检查特殊决策工具',
            'rule': '使用 Confirm、Deny 或 Select 时，必须满足 special_tool_rules',
        },
    ],
    'special_tool_rules': {
        'Confirm': (
            '助手正在请求确认，且用户当前明确表示同意；若用户转而提出新问题或新要求则不适用'
        ),
        'Deny': (
            '助手正在请求确认，且用户当前明确表示拒绝；若用户转而提出新问题或新要求则不适用'
        ),
        'Select': (
            '助手正在要求从候选项中选择，且用户通过序号、名称、描述或其他明确方式选中一项；'
            '仅提到某个对象不等于正在选择'
        ),
    },
    'risk_signals': {
        'usage': '以下信号只用于重点复核，不能脱离上下文机械判错',
        'items': [
            '用户重复表达或纠正同一诉求，但当前工具仍延续先前未解决诉求的理解',
            '用户已经明确切换任务，但当前工具仍在处理旧任务',
            '用户提出多个指令，而当前工具集合只覆盖其中一部分',
            '当前工具和用户诉求属于相近但不同的最终动作，例如路线导航、地点搜索和叫车',
            '工具描述只能完成相关操作，不能完成用户真正要求的结果',
            '工具池中存在更直接的工具，而当前选择使用了更泛化或更间接的工具',
        ],
    },
    'decision': {
        'match': 'evaluation_order 中的规则全部满足',
        'not_match': '任一规则不满足，或上下文不足以确认工具适用',
    },
}

QUESTION = {
    'tool_select_judge': {
        'type': 'noul',
        'instructions': (
            '按照 state.policy 的顺序进行判断：当前选中工具集合是否完整、准确地满足'
            '用户当前真实诉求？'
        ),
        'criteria': {
            'true': 'state.policy.evaluation_order 中的规则全部满足',
            'false': '任一规则不满足，或上下文不足以确认工具适用',
        },
    }
}


def _normalize_tools(tools):
    """工具列表 -> 仅含 name、description 的结构化工具列表。"""
    return [
        {
            'name': str(tool.get('name', '')),
            'description': str(tool.get('description', '')),
        }
        for tool in tools
        if isinstance(tool, dict) and tool.get('name')
    ]


def _selected_tool_names(tools):
    """保留选中工具的顺序和重复调用，只移除描述与其他字段。"""
    return [
        str(tool.get('name'))
        for tool in tools
        if isinstance(tool, dict) and tool.get('name')
    ]


def _pool_tools(old_state):
    """合并选中工具和其余候选，过滤条件工具并按工具名去重。"""
    pool = []
    seen_names = set()
    selected_tools = list(old_state.get('tools') or [])
    other_candidates = list(old_state.get('other_candidates') or [])

    # 被选中的工具始终进入工具池。
    for tool in selected_tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get('name', ''))
        if not name or name in seen_names:
            continue
        pool.append(tool)
        seen_names.add(name)

    # 只过滤其余候选中的 Event 条件工具。
    for tool in other_candidates:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get('name', ''))
        if not name or name.endswith('Event') or name in seen_names:
            continue
        pool.append(tool)
        seen_names.add(name)
    return pool


def _tool_reply(content):
    """从 tool 消息中提取助手可见回复，取不到时返回默认回复。"""
    if isinstance(content, (list, dict)):
        parsed = content
    else:
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return DEFAULT_TOOL_REPLY

    items = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        assistant_reply = item.get('assistantReply') or {}
        if not isinstance(assistant_reply, dict):
            assistant_reply = {}
        for text in (item.get('responseText'), assistant_reply.get('text')):
            if text and str(text).strip():
                return str(text).strip()
    return DEFAULT_TOOL_REPLY


def build_state(old_state):
    """将 round12 的 state dict 转换为新版结构化 state。"""
    conversation = []
    messages = old_state.get('messages') or []
    last_user_index = max(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, dict) and message.get('role') == 'user'
        ),
        default=-1,
    )
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        content = message.get('content') or ''
        if role == 'user':
            conversation.append({
                'role': 'user',
                'content': str(content),
                'is_current': index == last_user_index,
            })
        elif role == 'tool':
            conversation.append({
                'role': 'assistant',
                'content': _tool_reply(content),
            })

    return {
        'task': TASK,
        'available_tools': _normalize_tools(_pool_tools(old_state)),
        'conversation': conversation,
        'selected_tools': _selected_tool_names(old_state.get('tools') or []),
        'policy': POLICY,
    }


def transform(record):
    """将一条 round12 记录转换为新版记录。"""
    old_state = record['body']['state']
    result = {
        'session': {'sessionId': 'testsigma-prompt'},
        'body': {
            'model': 'jev-latest',
            'state': build_state(old_state),
            'questions': QUESTION,
        },
    }

    # 评估/追溯字段原样保留；不存在的可选字段保留为 null。
    required_fields = ('label', 'source', 'case_index', 'query', 'model_output', 'id', 'plan')
    optional_fields = ('sheet', 'domain', 'turn', 'output_type')
    result.update({field: record[field] for field in required_fields})
    result.update({field: record.get(field) for field in optional_fields})
    return result


def main():
    parser = argparse.ArgumentParser(
        description='round12 jsonl -> 新版结构化 state 格式 jsonl'
    )
    parser.add_argument(
        '--input',
        default=r'D:\任务\jev\data\round12\jev_eval_old.jsonl',
    )
    parser.add_argument(
        '--out',
        default=r'D:\任务\jev\data\round15\jev_eval_old.jsonl',
    )
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as source:
        records = [json.loads(line) for line in source if line.strip()]
    output_records = [transform(record) for record in records]

    output_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(output_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as target:
        for record in output_records:
            target.write(json.dumps(record, ensure_ascii=False) + '\n')

    print('read %d -> written %d -> %s' % (len(records), len(output_records), args.out))

    invalid_body = sum(
        1
        for record in output_records
        if not record['body']['state'] or not record['body']['questions']
    )
    missing_current_user = sum(
        1
        for record in output_records
        if not any(
            message.get('role') == 'user' and message.get('is_current')
            for message in record['body']['state'].get('conversation', [])
        )
    )
    missing_selected = sum(
        1
        for record in output_records
        if not record['body']['state'].get('selected_tools')
    )
    print('[校验] state/questions 非空:', invalid_body == 0)
    print(
        '[校验] 每条含当前用户输入:',
        missing_current_user == 0,
        '(缺失 %d)' % missing_current_user,
    )
    print(
        '[校验] 每条选中工具区非空:',
        missing_selected == 0,
        '(缺失 %d)' % missing_selected,
    )
    print('[校验] label 分布:', dict(Counter(r['label'] for r in output_records)))


if __name__ == '__main__':
    main()
