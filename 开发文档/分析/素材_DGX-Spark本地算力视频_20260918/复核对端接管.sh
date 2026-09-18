#!/bin/bash
# 复核：句柄是否真被使用 + 用大一点的模型做确定性问答
TOKEN=$(plutil -extract EnvironmentVariables.系统库网关凭证 raw -o - ~/Library/LaunchAgents/com.huashi.gateway-40007.plist)
GW="http://127.0.0.1:40007/网关/调用"
call() { curl -s -m 240 -X POST "$GW" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d "$1"; }

echo "=== 1) 连接 ollama 的 qwen2.5-14b（本地已跑，仅给 url）==="
R=$(call '{"操作":"调用能力","能力id":"大语言模型支持库.模型连接器.连接LLM","参数":{"模型":"qwen2.5-14b:latest","部署形态":"本地","url":"http://127.0.0.1:11434/v1","协议":"chat_completions","超时秒":180}}')
H=$(echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('值') or {}; print(v.get('句柄') or '')")
echo "  连接成功=$(echo "$R" | python3 -c "import json,sys; print(json.load(sys.stdin).get('成功'))")  句柄=$H  模型=$(echo "$R" | python3 -c "import json,sys; print((json.load(sys.stdin).get('值') or {}).get('模型'))")"

echo
echo "=== 2) 用有效句柄做确定性提问 ==="
call "{\"操作\":\"调用能力\",\"能力id\":\"大语言模型支持库.模型连接器.生成对话\",\"参数\":{\"句柄\":$H,\"消息列表\":[{\"角色\":\"用户\",\"内容\":\"回答两个字：收到\"}],\"最大令牌数\":24,\"温度\":0}}" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('值') or {}; print('  成功:',d.get('成功'),'错误码:',d.get('错误码')); print('  回复:',str(v.get('内容'))[:120]); print('  用量:',json.dumps(v.get('用量'),ensure_ascii=False)[:120])"

echo
echo "=== 3) 反向验证：故意用不存在的句柄，必须失败 ==="
call '{"操作":"调用能力","能力id":"大语言模型支持库.模型连接器.生成对话","参数":{"句柄":999999,"消息列表":[{"角色":"用户","内容":"收到"}],"最大令牌数":8}}' | python3 -c "import json,sys; d=json.load(sys.stdin); print('  成功:',d.get('成功'),'| 错误码:',d.get('错误码'),'| 说明:',d.get('错误说明'))"

echo
echo "=== 4) 撤销：确认没留下孤儿进程（底座没自己拉起进程）==="
call "{\"操作\":\"调用能力\",\"能力id\":\"大语言模型支持库.模型连接器.释放句柄\",\"参数\":{\"句柄\":$H}}" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  释放:',d.get('成功'),d.get('错误码'))"
echo "  ollama 仍在跑: $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:11434/v1/models)"
