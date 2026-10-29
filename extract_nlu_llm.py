# -*- coding: utf-8 -*-
"""从日志 JSONL 中提取基础字段和指定模型调用信息。

输入目录中的每个 .jsonl 会在输出目录生成同相对路径的 .jsonl。
每条输出保留 asrText、sessionId、interactionId 等基础字段，并把
nluResults 中符合条件的模型记录整理到 llm 列表。

每个文件内以 sessionId + interactionId 为唯一键。重复时优先保留 llm 中
包含 promptId=jev 的记录；若重复记录都包含或都不包含，则保留靠前的一条。

llm 只保留以下 llmModelInfos 元素：
1. promptId 为 DOMAIN_SELECT_TURBO_PY_PRO；
2. promptId 为 TOOL_AND_EVENT_SELECT_PY_PRO；
3. 没有 promptId 的元素，输出时标记为 jev。
"""
import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path


if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


BASE_FIELDS = (
    'asrText',
    'intent',
    'speakText',
    'deviceModel',
    'sysVersion',
    'time',
    'sessionId',
    'interactionId',
)

TARGET_PROMPT_IDS = {
    'DOMAIN_SELECT_TURBO_PY_PRO',
    'TOOL_AND_EVENT_SELECT_PY_PRO',
}


def _load_json_value(value):
    """字符串按 JSON 解析；对象原样返回。解析失败时返回 None。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return value


def _as_text(value):
    """保留原始字符串；结构化值再序列化为字符串。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _as_dict(value):
    parsed = _load_json_value(value)
    return parsed if isinstance(parsed, dict) else {}


def _field(record, name):
    value = record.get(name, '')
    return '' if value is None else value


def _llm_item(info):
    """把一条符合条件的 llmModelInfos 元素转成输出结构。"""
    if not isinstance(info, dict):
        return None

    model_param = _as_dict(info.get('modelParam'))
    prompt_id = info.get('promptId')
    has_prompt_id = 'promptId' in info and prompt_id not in (None, '')

    if not has_prompt_id:
        return {
            'promptId': 'jev',
            'prompt': _as_text(info.get('prompt')),
            'llmText': _as_text(info.get('llmText')),
            'errorMessage': _as_text(model_param.get('errorMessage')),
        }

    if prompt_id not in TARGET_PROMPT_IDS:
        return None

    return {
        'promptId': prompt_id,
        'prompt': _as_text(info.get('prompt')),
        'llmText': _as_text(info.get('llmText')),
        'modelVersion': _as_text(model_param.get('modelVersion')),
    }


def extract_llm(nlu_results):
    """从 nluResults 中按顺序提取目标模型记录。"""
    parsed = _load_json_value(nlu_results)
    if not isinstance(parsed, list):
        raise ValueError('nluResults 不是 JSON 列表')

    items = []
    for entry in parsed:
        if not isinstance(entry, dict) or 'llmModelInfos' not in entry:
            continue
        infos = _load_json_value(entry.get('llmModelInfos'))
        if not isinstance(infos, list):
            continue
        for info in infos:
            item = _llm_item(info)
            if item is not None:
                items.append(item)
    return items


def transform(record):
    """提取一条原始日志。nluResults 无法解析时保留基础字段并返回空 llm。"""
    output = {name: _field(record, name) for name in BASE_FIELDS}
    try:
        output['llm'] = extract_llm(record.get('nluResults'))
        return output, None
    except ValueError as exc:
        output['llm'] = []
        return output, str(exc)


def _has_jev(record):
    return any(item.get('promptId') == 'jev' for item in record.get('llm') or [])


def _unique_key(record):
    return (str(record.get('sessionId', '')), str(record.get('interactionId', '')))


def dedupe_records(records):
    """按文件内唯一键去重，返回保留记录和被去掉的数量。"""
    selected = {}
    for record in records:
        key = _unique_key(record)
        current = selected.get(key)
        if current is None or (_has_jev(record) and not _has_jev(current)):
            selected[key] = record

    kept = []
    seen = set()
    for record in records:
        key = _unique_key(record)
        if key in seen:
            continue
        seen.add(key)
        kept.append(selected[key])
    return kept, len(records) - len(kept)


def iter_jsonl_files(input_dir):
    return sorted(
        path for path in input_dir.rglob('*')
        if path.is_file() and path.suffix.lower() == '.jsonl'
    )


def process_file(source, target):
    """处理一个 JSONL 文件并返回统计信息。"""
    stats = Counter()
    outputs = []
    target.parent.mkdir(parents=True, exist_ok=True)

    with source.open(encoding='utf-8') as src:
        for line_no, line in enumerate(src, start=1):
            if not line.strip():
                continue
            stats['records'] += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                stats['bad_json'] += 1
                print('[跳过] %s:%d JSON 解析失败' % (source, line_no), file=sys.stderr)
                continue
            if not isinstance(record, dict):
                stats['bad_json'] += 1
                print('[跳过] %s:%d 不是 JSON 对象' % (source, line_no), file=sys.stderr)
                continue

            output, error = transform(record)
            if error:
                stats['bad_nlu'] += 1
                print('[警告] %s:%d %s' % (source, line_no, error), file=sys.stderr)
            outputs.append(output)

    kept, dropped = dedupe_records(outputs)
    stats['duplicates'] += dropped
    with target.open('w', encoding='utf-8') as dst:
        for output in kept:
            for item in output['llm']:
                stats['llm:' + item['promptId']] += 1
            if output['llm']:
                stats['records_with_llm'] += 1
            dst.write(json.dumps(output, ensure_ascii=False) + '\n')
            stats['written'] += 1
    return stats


def _cli_argv(argv=None):
    """去掉 Jupyter 内核注入的 -f kernel.json，避免 argparse 误判。"""
    if argv is None:
        argv = sys.argv[1:]
    cleaned = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg == '-f':
            skip_next = True
            continue
        cleaned.append(arg)
    return cleaned


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='extract_nlu_llm.py',
        description='提取 JSONL 日志中的基础字段和目标模型调用',
    )
    parser.add_argument('--input-dir', required=True, help='包含原始 JSONL 的文件夹')
    parser.add_argument('--output-dir', required=True, help='保存提取结果的文件夹')
    args = parser.parse_args(_cli_argv(argv))

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not input_dir.is_dir():
        parser.error('输入目录不存在: %s' % input_dir)
    if output_dir == input_dir or input_dir in output_dir.parents:
        parser.error('输出目录不能与输入目录相同，也不能位于输入目录内')

    files = iter_jsonl_files(input_dir)
    if not files:
        print('未找到 JSONL 文件: %s' % input_dir)
        return

    total = Counter()
    for source in files:
        target = output_dir / source.relative_to(input_dir)
        stats = process_file(source, target)
        total.update(stats)
        print('%s -> %s (%d 条)' % (source, target, stats['written']))

    print('[完成] 文件 %d，写出 %d，含模型记录 %d' % (
        len(files), total['written'], total['records_with_llm']))
    print('[完成] JSON 失败 %d，nluResults 失败 %d，重复键去掉 %d' % (
        total['bad_json'], total['bad_nlu'], total['duplicates']))
    llm_counts = {
        key.split(':', 1)[1]: count
        for key, count in sorted(total.items())
        if key.startswith('llm:')
    }
    print('[完成] llm 分布:', llm_counts)


if __name__ == '__main__':
    main()
