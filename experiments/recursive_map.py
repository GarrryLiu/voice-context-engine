"""Explicit paid semantic hierarchy smoke using synthetic text and a temporary DB."""
import argparse
import json,tempfile
from pathlib import Path
from voice_context.server.demo import DemoService
from voice_context.server.map_provider import OpenAIMapProvider
from voice_context.product.semantic_maps import SemanticMaps
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--env-file',required=True);parser.add_argument('--output',default='experiments/recursive-map-results.json');args=parser.parse_args()
texts=['今天完整讨论语音产品的发布。产品规划下面有用户旅程和定价两部分。用户旅程里分通勤学习和办公室复盘。','通勤学习的核心是不用看屏幕，听懂一份材料后留下自己的理解笔记。办公室复盘主要整理当天的决定和待办。','技术方案是另一个部分，里面有实时语音和记忆存储。实时语音需要支持打断，记忆存储需要保留原始发言和修改历史。','今天决定先做好通勤学习，定价还没决定。不要把办公室复盘也当成已经决定上线。']
with tempfile.TemporaryDirectory() as root:
    service=DemoService(str(Path(root)/'test.db'))
    try:
        for text in texts:service.submit_demo('test',text)
        provider=OpenAIMapProvider(args.env_file);maps=SemanticMaps(service.product.access,provider)
        result=maps.propose('test','main');saved=maps.apply('test',result['id'])
        def depth(item):return 1+max((depth(n) for n in item.get('nodes',[])),default=0)
        report={'mode':'Synthetic Chinese conversation, real map model, temporary database; parent structure source-validated, not a general semantic quality evaluation.','sources':texts,'model_call':provider.last_call,'proposal':result['proposal'],'root_sessions':len(saved['workspace']['data']['sessions']),'max_node_levels':max(depth(n) for n in saved['workspace']['data']['sessions'])}
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ['model_call','root_sessions','max_node_levels']},ensure_ascii=False))
    finally:service.close()
