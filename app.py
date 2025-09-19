from flask import Flask, request, render_template_string
import os, requests, time, random, string, json, atexit
from threading import Thread, Event
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'AJEET_SECRET_KEY'
app.debug = True

headers = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': '/',
    'Accept-Language': 'en-US,en;q=0.9',
}

stop_events, threads, active_users = {}, {}, {}
TASK_FILE = 'tasks.json'

def save_tasks():
    with open(TASK_FILE, 'w', encoding='utf-8') as f:
        json.dump(active_users, f, ensure_ascii=False, indent=2)

def load_tasks():
    if not os.path.exists(TASK_FILE): return
    with open(TASK_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for tid, info in data.items():
            active_users[tid] = info
            stop_events[tid] = Event()
            if info.get('status') == 'ACTIVE':
                if not info.get('fb_name'):
                    info['fb_name'] = fetch_profile_name(info['token'])
                th = Thread(
                    target=send_messages,
                    args=(
                        info['tokens_all'],
                        info['thread_id'],
                        info['name'],
                        info.get('delay', 1),
                        info['msgs'],
                        tid
                    ),
                    daemon=True
                )
                th.start()
                threads[tid] = th

atexit.register(save_tasks)
load_tasks()

def check_token_health(token):
    """Check if a token is valid and return its status"""
    try:
        res = requests.get(
            f'https://graph.facebook.com/me?access_token={token}',
            timeout=8
        )
        data = res.json()
        
        if 'error' in data:
            return {
                'valid': False,
                'error': data['error']['message'],
                'name': 'INVALID TOKEN'
            }
        else:
            # Get additional token info
            expiry_info = requests.get(
                f'https://graph.facebook.com/v15.0/debug_token?input_token={token}&access_token={token}',
                timeout=8
            )
            expiry_data = expiry_info.json()
            
            expires_at = expiry_data.get('data', {}).get('expires_at', 0)
            if expires_at:
                expiry_date = datetime.fromtimestamp(expires_at)
                time_remaining = expiry_date - datetime.now()
                expiry_status = f"Expires: {expiry_date.strftime('%Y-%m-%d')} ({time_remaining.days} days left)"
            else:
                expiry_status = "Long-lived token"
                
            return {
                'valid': True,
                'name': data.get('name', 'Unknown'),
                'id': data.get('id', 'Unknown'),
                'expiry': expiry_status
            }
    except Exception as e:
        return {
            'valid': False,
            'error': str(e),
            'name': 'CHECK FAILED'
        }

def fetch_profile_name(token: str) -> str:
    try:
        res = requests.get(
            f'https://graph.facebook.com/me?access_token={token}',
            timeout=8
        )
        return res.json().get('name', 'Unknown')
    except Exception:
        return 'Unknown'

def send_messages(tokens, thread_id, mn, delay, messages, task_id):
    ev = stop_events[task_id]
    tok_i, msg_i = 0, 0
    total_tok, total_msg = len(tokens), len(messages)
    
    # Token health monitoring
    token_statuses = [check_token_health(token) for token in tokens]
    active_users[task_id]['token_statuses'] = token_statuses
    active_users[task_id]['last_health_check'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Count valid tokens
    valid_tokens = sum(1 for status in token_statuses if status['valid'])
    active_users[task_id]['valid_tokens'] = valid_tokens
    
    while not ev.is_set():
        tk = tokens[tok_i]
        msg = messages[msg_i]
        try:
            requests.post(
                f'https://graph.facebook.com/v15.0/t_{thread_id}/',
                data={'access_token': tk, 'message': f"{mn} {msg}"},
                headers=headers,
                timeout=10
            )
            print(f"[✔️ SENT] {msg[:40]} via TOKEN-{tok_i+1}")
            
            # Update token last used time
            if 'token_last_used' not in active_users[task_id]:
                active_users[task_id]['token_last_used'] = {}
            active_users[task_id]['token_last_used'][str(tok_i)] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
        except Exception as e:
            print("[⚠️ ERROR]", e)
            
            # Mark token as potentially problematic
            if 'token_errors' not in active_users[task_id]:
                active_users[task_id]['token_errors'] = {}
            active_users[task_id]['token_errors'][str(tok_i)] = active_users[task_id].get('token_errors', {}).get(str(tok_i), 0) + 1
            
        tok_i = (tok_i + 1) % total_tok
        msg_i = (msg_i + 1) % total_msg
        time.sleep(delay)

@app.route('/', methods=['GET', 'POST'])
def home():
    msg_html = stop_html = ""
    if request.method == 'POST':
        if 'txtFile' in request.files:
            tokens = (
                [request.form.get('singleToken').strip()]
                if request.form.get('tokenOption') == 'single'
                else request.files['tokenFile'].read()
                .decode(errors='ignore')
                .splitlines()
            )
            tokens = [t for t in tokens if t]
            uid = request.form.get('threadId','').strip()
            hater = request.form.get('kidx','').strip()
            delay = max(int(request.form.get('time',1) or 1),1)
            file = request.files['txtFile']
            msgs = [m for m in file.read().decode(errors='ignore').splitlines() if m]
            if not (tokens and uid and hater and msgs):
                msg_html = "<div class='alert alert-danger rounded-pill p-2'>⚠️ All fields required!</div>"
            else:
                tid = 'SM9K3R' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                stop_events[tid] = Event()
                
                # Check token health before starting
                token_statuses = [check_token_health(token) for token in tokens]
                valid_tokens = sum(1 for status in token_statuses if status['valid'])
                
                th = Thread(
                    target=send_messages,
                    args=(tokens, uid, hater, delay, msgs, tid),
                    daemon=True
                )
                th.start()
                threads[tid] = th
                active_users[tid] = {
                    'name': hater,
                    'token': tokens[0],
                    'tokens_all': tokens,
                    'fb_name': fetch_profile_name(tokens[0]),
                    'thread_id': uid,
                    'msg_file': file.filename or 'messages.txt',
                    'msgs': msgs,
                    'delay': delay,
                    'msg_count': len(msgs),
                    'status': 'ACTIVE',
                    'token_statuses': token_statuses,
                    'valid_tokens': valid_tokens,
                    'total_tokens': len(tokens),
                    'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'last_health_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                save_tasks()
                
                health_status = f"<div class='health-status' style='margin-top: 10px; padding: 10px; background: #2d2d2d; border-radius: 8px;'>"
                health_status += f"<b>Token Health:</b> {valid_tokens}/{len(tokens)} valid tokens<br>"
                for i, status in enumerate(token_statuses):
                    status_icon = "✅" if status['valid'] else "❌"
                    health_status += f"Token {i+1}: {status_icon} {status['name']}<br>"
                health_status += "</div>"
                
                msg_html = f"""
                <div class='stop-key rounded-pill p-3'>🔑 <b>STOP KEY↷</b><br><code>{tid}</code></div>
                {health_status}
                """
        elif 'taskId' in request.form:
            tid = request.form.get('taskId','').strip()
            if tid in stop_events:
                stop_events[tid].set()
                if tid in active_users:
                    active_users[tid]['status'] = 'OFFLINE'
                    active_users[tid]['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                save_tasks()
                stop_html = "<div class='stop-ok rounded-pill p-3'>⏹️ <b>STOPPED</b><br><code>{}</code></div>".format(tid)
            else:
                stop_html = "<div class='stop-bad rounded-pill p-3'>❌ <b>INVALID KEY</b><br><code>{}</code></div>".format(tid)
    
    # Display active tasks with health status
    active_tasks_html = ""
    if active_users:
        active_tasks_html = "<div class='divider'></div><h5 class='text-center mt-4' style='color: var(--gold-yellow);'>ACTIVE TASKS</h5>"
        for tid, info in active_users.items():
            if info.get('status') == 'ACTIVE':
                valid_tokens = info.get('valid_tokens', 0)
                total_tokens = info.get('total_tokens', 0)
                status_color = "text-success" if valid_tokens > 0 else "text-danger"
                
                active_tasks_html += f"""
                <div class='task-item p-3 mb-2' style='background: #2d2d2d; border-radius: 8px;'>
                    <b>Task ID:</b> <code>{tid}</code><br>
                    <b>Target:</b> {info.get('thread_id', 'N/A')}<br>
                    <b>Hater Name:</b> {info.get('name', 'N/A')}<br>
                    <b>Tokens:</b> <span class='{status_color}'>{valid_tokens}/{total_tokens} valid</span><br>
                    <b>Started:</b> {info.get('start_time', 'N/A')}
                </div>
                """
    
    return render_template_string(html_template, msg_html=msg_html, stop_html=stop_html, active_tasks_html=active_tasks_html)

html_template = '''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>⚔️ 𝗧𝗛𝗪 𝗟𝗘𝗚𝗘𝗡𝗗 𝗪𝗔𝗟𝗘𝗘𝗗 𝗞𝗜𝗡𝗚 ⚔️</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
  <style>
    :root {
      --dark-gray: #1a1a1a;
      --medium-gray: #2d2d2d;
      --light-gray: #3c3c3c;
      --gold-yellow: #ffd700;
      --light-yellow: #fff9c4;
    }
    
    body {
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 20px;
      color: #fff;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(135deg, var(--dark-gray) 0%, #000000 100%);
    }
    
    .card-dark {
      background: var(--medium-gray);
      border: 2px solid var(--gold-yellow);
      border-radius: 15px;
      padding: 25px;
      box-shadow: 0 0 20px rgba(255, 215, 0, 0.3);
      width: 100%;
      max-width: 650px;
    }
    
    .card-title {
      color: var(--gold-yellow);
      text-align: center;
      margin-bottom: 25px;
      font-weight: bold;
      text-shadow: 0 0 10px rgba(255, 215, 0, 0.5);
    }
    
    .form-label {
      color: var(--light-yellow);
      font-weight: 500;
      margin-bottom: 8px;
    }
    
    .form-control {
      background-color: var(--light-gray);
      border: 1px solid #555;
      color: white;
      border-radius: 8px;
      padding: 12px 15px;
    }
    
    .form-control:focus {
      background-color: var(--light-gray);
      border-color: var(--gold-yellow);
      box-shadow: 0 0 0 0.25rem rgba(255, 215, 0, 0.25);
      color: white;
    }
    
    .btn-option {
      background-color: var(--light-gray);
      border: 1px solid #555;
      color: #ccc;
      border-radius: 8px;
      padding: 10px 15px;
      margin: 5px;
      transition: all 0.3s;
    }
    
    .btn-option:hover, .btn-option.active {
      background-color: var(--gold-yellow);
      color: var(--dark-gray);
      border-color: var(--gold-yellow);
      font-weight: bold;
    }
    
    .btn-primary-custom {
      background: linear-gradient(to bottom, var(--gold-yellow), #ffaa00);
      color: #000;
      border: none;
      border-radius: 8px;
      padding: 12px 25px;
      font-weight: bold;
      transition: all 0.3s;
      width: 100%;
    }
    
    .btn-primary-custom:hover {
      background: linear-gradient(to bottom, #ffaa00, var(--gold-yellow));
      transform: translateY(-2px);
      box-shadow: 0 5px 15px rgba(255, 215, 0, 0.4);
    }
    
    .btn-danger-custom {
      background: linear-gradient(to bottom, #ff4d4d, #cc0000);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 12px 25px;
      font-weight: bold;
      transition: all 0.3s;
      width: 100%;
    }
    
    .btn-danger-custom:hover {
      background: linear-gradient(to bottom, #cc0000, #ff4d4d);
      transform: translateY(-2px);
      box-shadow: 0 5px 15px rgba(255, 0, 0, 0.4);
    }
    
    .option-group {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      margin-bottom: 15px;
    }
    
    .option-group label {
      margin: 0 5px;
    }
    
    .stop-key, .stop-ok, .stop-bad {
      margin-top: 20px;
      border-radius: 10px;
      border: 2px solid var(--gold-yellow);
      text-align: center;
      font-size: 1rem;
      padding: 15px;
    }
    
    .stop-key {
      background: var(--dark-gray); 
      color: var(--gold-yellow);
    }
    
    .stop-ok {
      background: var(--dark-gray);
      color: #4CAF50;
      border-color: #4CAF50;
    }
    
    .stop-bad {
      background: var(--dark-gray);
      color: #f44336;
      border-color: #f44336;
    }
    
    .divider {
      height: 1px;
      background: linear-gradient(to right, transparent, var(--gold-yellow), transparent);
      margin: 25px 0;
    }
    
    .feature-badge {
      background-color: var(--gold-yellow);
      color: var(--dark-gray);
      border-radius: 20px;
      padding: 5px 12px;
      font-weight: bold;
      margin-right: 8px;
      font-size: 0.8rem;
    }
    
    .health-status {
      margin-top: 15px;
      padding: 12px;
      background: var(--dark-gray);
      border-radius: 8px;
      border: 1px solid var(--gold-yellow);
      font-size: 0.9rem;
    }
    
    .task-item {
      background: var(--dark-gray);
      border-radius: 8px;
      border: 1px solid #444;
      margin-bottom: 10px;
      font-size: 0.9rem;
    }
  </style>
  <script>
    function toggleTokenOption(type) {
      document.getElementById('singleTokenDiv').style.display = (type==='single')?'block':'none';
      document.getElementById('tokenFileDiv').style.display = (type==='file')?'block':'none';
    }
    
    function toggleOption(button, option) {
      // Remove active class from all buttons in the same group
      const buttons = button.parentElement.querySelectorAll('.btn-option');
      buttons.forEach(btn => btn.classList.remove('active'));
      
      // Add active class to clicked button
      button.classList.add('active');
      
      // Set the hidden input value
      document.getElementById('modeOption').value = option;
    }
  </script>
</head>
<body>
  <div class="container p-0">
    <div class="card-dark">
      <h2 class="card-title"><i class="fas fa-crown"></i> 𝗧𝗛𝗪 𝗟𝗘𝗚𝗘𝗡𝗗 𝗪𝗔𝗟𝗘𝗘𝗗 𝗞𝗜𝗡𝗚 ⚔️</h2>
      
      <div class="option-group">
        <span class="feature-badge">MODE</span>
        <button type="button" class="btn-option active" onclick="toggleOption(this, 'standard')">Standard</button>
        <button type="button" class="btn-option" onclick="toggleOption(this, 'advanced')">Advanced</button>
        <button type="button" class="btn-option" onclick="toggleOption(this, 'stealth')">Stealth</button>
      </div>
      
      <input type="hidden" id="modeOption" name="modeOption" value="standard">
      
      <form method="POST" enctype="multipart/form-data">
        <div class="mb-3">
          <label class="form-label">TOKEN OPTION</label>
          <div class="option-group">
            <div class="form-check form-check-inline">
              <input class="form-check-input" type="radio" name="tokenOption" id="singleToken" value="single" checked onclick="toggleTokenOption('single')">
              <label class="form-check-label" for="singleToken">Single Token</label>
            </div>
            <div class="form-check form-check-inline">
              <input class="form-check-input" type="radio" name="tokenOption" id="fileToken" value="file" onclick="toggleTokenOption('file')">
              <label class="form-check-label" for="fileToken">Token File</label>
            </div>
          </div>
        </div>
        
        <div id="singleTokenDiv" class="mb-3">
          <label class="form-label"><i class="fas fa-key"></i> Enter Single Token</label>
          <input type="text" name="singleToken" class="form-control" placeholder="Enter single token">
        </div>
        
        <div id="tokenFileDiv" style="display:none" class="mb-3">
          <label class="form-label"><i class="fas fa-file-alt"></i> Upload Token File</label>
          <input type="file" name="tokenFile" class="form-control" accept=".txt">
        </div>
        
        <div class="mb-3">
          <label class="form-label"><i class="fas fa-comments"></i> Conversation ID</label>
          <input type="text" name="threadId" class="form-control" placeholder="Conversation ID" required>
        </div>
        
        <div class="mb-3">
          <label class="form-label"><i class="fas fa-user-secret"></i> Hater Name</label>
          <input type="text" name="kidx" class="form-control" placeholder="Hater Name" required>
        </div>
        
        <div class="mb-3">
          <label class="form-label"><i class="fas fa-tachometer-alt"></i> Speed (in seconds)</label>
          <input type="number" name="time" class="form-control" placeholder="Speed (seconds)" min="1" required>
        </div>
        
        <div class="mb-3">
          <label class="form-label"><i class="fas fa-envelope"></i> Message File (.txt)</label>
          <input type="file" name="txtFile" class="form-control" accept=".txt" required>
        </div>
        
        <div class="text-center mb-4">
          <button type="submit" class="btn btn-primary-custom"><i class="fas fa-rocket"></i> START BOMBING</button>
        </div>
      </form>
      
      {{msg_html|safe}}
      
      <div class="divider"></div>
      
      <form method="POST">
        <div class="mb-3">
          <label class="form-label"><i class="fas fa-stop-circle"></i> Enter STOP KEY</label>
          <input type="text" name="taskId" class="form-control" placeholder="Enter STOP KEY" required>
        </div>
        
        <div class="text-center">
          <button type="submit" class="btn btn-danger-custom"><i class="fas fa-stop"></i> STOP BOMBING</button>
        </div>
      </form>
      
      {{stop_html|safe}}
      
      {{active_tasks_html|safe}}
    </div>
  </div>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)