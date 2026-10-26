let sid = {{ cur.id if cur else 'null' }};

function append(text, who) {
  const box = document.getElementById('chatBox');
  const div = document.createElement('div');
  div.style.marginBottom = '14px';
  div.style.textAlign = who === 'user' ? 'right' : 'left';
  const bubble = document.createElement('div');
  bubble.style.display = 'inline-block';
  bubble.style.maxWidth = '72%';
  bubble.style.padding = '10px 14px';
  bubble.style.borderRadius = '12px';
  bubble.style.whiteSpace = 'pre-wrap';
  bubble.style.textAlign = 'left';
  bubble.style.fontSize = '14px';
  if (who === 'user') {
    bubble.style.background = '#1d8aa8'; bubble.style.color = '#fff';
  } else {
    bubble.style.background = '#fff'; bubble.style.border = '1px solid #e3ebf1';
  }
  bubble.textContent = text;
  div.appendChild(bubble);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

async function send() {
  const input = document.getElementById('msgInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  append(text, 'user');
  document.getElementById('sendBtn').disabled = true;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: text, sid: sid})
    });
    const data = await res.json();
    if (data.ok) {
      sid = data.sid;
      append(data.reply, 'assistant');
      if (data.risk === 'high') {
        const tip = document.createElement('div');
        tip.style.cssText = 'background:#fdeaea;color:#b23b3b;font-size:12px;padding:8px 12px;border-radius:8px;margin-top:6px;text-align:left';
        tip.textContent = '⚠ 系统已识别到高危信号并通知学校心理中心；如需立即帮助请拨打 400-161-9995';
        document.querySelector('#chatBox').appendChild(tip);
      }
    }
  } catch (e) {
    append('网络异常，请稍后重试。', 'assistant');
  }
  document.getElementById('sendBtn').disabled = false;
}

document.getElementById('sendBtn').onclick = send;
document.getElementById('msgInput').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') send();
});
document.getElementById('newChat').onclick = function () {
  fetch('/api/chat/new', {method: 'POST'}).then(r => r.json()).then(d => {
    if (d.ok) location.href = '/chat?sid=' + d.sid;
  });
};
