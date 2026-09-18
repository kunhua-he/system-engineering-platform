#!/bin/bash
# 实测：底座能否接管本机已在运行的模型端点（不自己拉起进程）
TOKEN=$(plutil -extract EnvironmentVariables.系统库网关凭证 raw -o - ~/Library/LaunchAgents/com.huashi.gateway-40007.plist)
GW="http://127.0.0.1:40007/网关/调用"

call() {
  curl -s -m 180 -X POST "$GW" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d "$1"
}

echo "=== 前提：ollama 11434 已跑 ==="
printf "  ollama /v1/models -> %s\n" "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:11434/v1/models)"

echo
echo "=== A：部署形态=本地 + url（接管已在跑的端点）==="
RA=$(call '{"操作":"调用能力","能力id":"大语言模型支持库.模型连接器.连接LLM","参数":{"模型":"gemma-3-1b:latest","部署形态":"本地","url":"http://127.0.0.1:11434/v1","协议":"chat_completions","超时秒":120}}')
echo "$RA" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  成功:',d.get('成功'),'| 错误码:',d.get('错误码'),'| 说明:',d.get('错误说明'),'| 句柄:',d.get('句柄'),'| 值:',json.dumps(d.get('值'),ensure_ascii=False)[:200])"
HA=$(echo "$RA" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('句柄') or (d.get('值') or {}).get('句柄') or '')")

echo
echo "=== B：部署形态=云端 + url（把本机端点当云端连）==="
RB=$(call '{"操作":"调用能力","能力id":"大语言模型支持库.模型连接器.连接LLM","参数":{"模型":"gemma-3-1b:latest","部署形态":"云端","url":"http://127.0.0.1:11434/v1","api_key":"123","协议":"chat_completions","超时秒":120}}')
echo "$RB" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  成功:',d.get('成功'),'| 错误码:',d.get('错误码'),'| 说明:',d.get('错误说明'),'| 句柄:',d.get('句柄'),'| 值:',json.dumps(d.get('值'),ensure_ascii=False)[:200])"
HB=$(echo "$RB" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('句柄') or (d.get('值') or {}).get('句柄') or '')")

TARGET=${HA:-$HB}
echo
echo "=== C：拿句柄做真实推理（句柄=$TARGET）==="
if [ -n "$TARGET" ]; then
  RC=$(call "{\"操作\":\"调用能力\",\"能力id\":\"大语言模型支持库.模型连接器.生成对话\",\"参数\":{\"句柄\":$TARGET,\"消息列表\":[{\"角色\":\"用户\",\"内容\":\"只回答两个字：收到\"}],\"最大令牌数\":32}}")
  echo "$RC" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  成功:',d.get('成功'),'| 错误码:',d.get('错误码'),'| 说明:',d.get('错误说明')); v=d.get('值') or {}; print('  回复:',str(v.get('内容') or v)[:200])"
  echo
  echo "=== D：释放句柄 ==="
  call "{\"操作\":\"调用能力\",\"能力id\":\"大语言模型支持库.模型连接器.释放句柄\",\"参数\":{\"句柄\":$TARGET}}" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  释放:',d.get('成功'),d.get('错误码'))"
else
  echo "  两种形态都没拿到句柄"
fi

echo
echo "=== E：本机端点有无被目录感知 ==="
for K in 已运行 端点池 局域网 发现模型服务; do
  printf "  %-10s: " "$K"
  call "{\"操作\":\"调用能力\",\"能力id\":\"能力目录.搜索能力\",\"参数\":{\"关键词\":\"$K\"}}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len((d.get('值') or {}).get('能力列表') or []),'条')"
done
