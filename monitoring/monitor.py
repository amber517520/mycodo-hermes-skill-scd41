"""Read-only monitoring. No device controls, credentials or network writes."""
import base64
import datetime as dt
import json
import math
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TZ=dt.timezone(dt.timedelta(hours=8))
CONTROL_RULES=json.loads((ROOT/'control_rules.json').read_text(encoding='utf-8'))

def notification_allowed(now):
    local=dt.datetime.fromtimestamp(now,TZ)
    return 9<=local.hour<21

def parse_names(names):
    if not any('SCD-4x (Input e0fe890e)' in n for n in names):
        raise ValueError('sensor_not_visible')
    result={}
    timestamps=[]
    keys={0:'co2',1:'temperature',2:'rh',3:'dew_point',4:'vpd'}
    for i,name in enumerate(names):
        m=re.search(r'\bCH([0-4])\s*\|',name)
        if not m: continue
        key=keys[int(m.group(1))]
        if key in result: raise ValueError('duplicate_channel')
        value=next((x.strip() for x in reversed(names[max(0,i-3):i]) if re.fullmatch(r'-?\d+(?:\.\d+)?',x.strip())),None)
        if value is None or i+1>=len(names): raise ValueError('missing_value')
        value=float(value)
        if not math.isfinite(value): raise ValueError('nonfinite')
        result[key]=value
        timestamps.append(dt.datetime.strptime(names[i+1].strip(),'%Y/%m/%d %H:%M:%S').replace(tzinfo=TZ).isoformat())
    if set(result)!=set(keys.values()) or len(set(timestamps))!=1: raise ValueError('incomplete_or_mixed_time')
    if not (0<=result['rh']<=100 and 0<=result['co2']<=1000000 and -40<=result['temperature']<=125): raise ValueError('invalid_range')
    result['timestamp']=timestamps[0]
    return result

RULES={
 'TEMP_HIGH':('temperature',lambda x:x>28,lambda x:x<=27,3,'溫度過高'),
 'TEMP_LOW':('temperature',lambda x:x<22,lambda x:x>=23,3,'溫度過低'),
 'RH_LOW':('rh',lambda x:x<80,lambda x:x>=80,3,'霧化器啟動候選成立（僅紀錄，未啟動設備）'),
 'RH_HIGH':('rh',lambda x:x>=90,lambda x:x<=88,1,'濕度已達90%，禁止追加加濕，需人工檢查（未發送Telegram）'),
 'CO2_HIGH':('co2',lambda x:x>=1000,lambda x:x<1000,3,'風扇啟動候選成立（僅紀錄，未啟動設備）'),
}

def evaluate(state,reading,now):
    s=json.loads(json.dumps(state))
    if s.get('policy_version')!=CONTROL_RULES['policy_version']:
        s['rules']={}
        s['policy_version']=CONTROL_RULES['policy_version']
    s.setdefault('started_at',now)
    s.setdefault('rules',{})
    alerts=[]
    def event(code,text):
        last=s.setdefault('event_notifications',{}).get(code)
        if last is None or now-last>=900:
            alerts.append(code+': '+text)
            s['event_notifications'][code]=now
    last=s.get('last_sample_epoch')
    stamp=None
    if reading is not None:
        stamp=dt.datetime.fromisoformat(reading['timestamp']).timestamp()
        if stamp>now or (last is not None and stamp<last):
            s['assessment_allowed']=False
            event('TIME_INVALID','感測時間異常，停止環境判斷。')
            reading=None
            s['recovering']=True
            s['fresh_count']=0
    age=now-(stamp if reading is not None else (last if last is not None else s['started_at']))
    if age>180 or reading is None:
        s['assessment_allowed']=False
        s['recovering']=True
        s['fresh_count']=0
        for r in s['rules'].values(): r.update(bad=0,good=0)
        if age>300:
            event('DATA_GAP','超過5分鐘無有效新資料；請檢查Mycodo頁面、感測器、電腦及網路。')
            s['gap_alerted']=True
        return s,alerts
    if stamp==last:
        return s,alerts
    gap=last is not None and stamp-last>90
    if gap:
        for r in s['rules'].values(): r.update(bad=0,good=0)
    s['last_sample_epoch']=stamp
    s['last_reading']=reading
    if s.get('recovering'):
        s['fresh_count']=1 if gap else s.get('fresh_count',0)+1
        s['assessment_allowed']=s['fresh_count']>=3
        if not s['assessment_allowed']: return s,alerts
        s['recovering']=False
        if s.pop('gap_alerted',False): alerts.append('DATA_RECOVERED: 已恢復連續3筆有效新資料。')
    s['assessment_allowed']=True
    for code,(key,bad,good,required,label) in RULES.items():
        r=s['rules'].setdefault(code,{'active':False,'bad':0,'good':0,'notified':None})
        value=reading[key]
        r['bad']=r['bad']+1 if bad(value) else 0
        r['good']=r['good']+1 if good(value) else 0
        if r['active'] and r['good']>=3:
            r['active']=False
            alerts.append(code+' RECOVERED: '+label+'提醒已解除。')
            r['notified']=None
        elif r['bad']>=required:
            r['active']=True
        if r['active'] and (r['notified'] is None or now-r['notified']>=900):
            alerts.append(code+': '+label+'；目前讀值 '+str(value))
            r['notified']=now
    return s,alerts

# Read only the named Mycodo live document; no input, credentials or GPIO.
PS_READ=r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
$root=[System.Windows.Automation.AutomationElement]::RootElement
$windows=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$names=$null
foreach($window in $windows){
 if($window.Current.Name -notlike '*Pi5-401*Mycodo*'){continue}
 if($Refresh){
  $bc=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Button)
  $buttons=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$bc)
  $reloaded=$false
  $zhReload=([string][char]0x91cd+[char]0x65b0+[char]0x8f09+[char]0x5165)
  foreach($button in $buttons){
   if($button.Current.Name -eq $zhReload -or $button.Current.Name -eq 'Reload'){
    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    $reloaded=$true; break
   }
  }
  if(-not $reloaded){throw 'Mycodo reload unavailable'}
  Start-Sleep -Milliseconds 1200
 }
 $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document)
 $docs=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
 foreach($doc in $docs){
  if($doc.Current.Name -notlike '*Pi5-401*Mycodo*'){continue}
  $items=$doc.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $candidate=@($items | ForEach-Object {$_.Current.Name})
  if(@($candidate | Where-Object {$_ -like '*SCD-4x (Input e0fe890e)*'}).Count -gt 0){$names=$candidate; break}
 }
 if($null -ne $names){break}
}
if($null -eq $names){throw 'Mycodo live document not available'}
$json=ConvertTo-Json -InputObject @($names) -Compress
[Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))
'''

def read_visible_names(refresh=False):
    prefix='$Refresh=$true\n' if refresh else '$Refresh=$false\n'
    encoded=base64.b64encode((prefix+PS_READ).encode('utf-16le')).decode('ascii')
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,timeout=25,creationflags=0x08000000)
    if r.returncode: raise ValueError('mycodo_document_unavailable')
    return json.loads(base64.b64decode(r.stdout.strip()).decode('utf-8'))

def tick(root,read_fn=None,now=None):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    now=dt.datetime.now(TZ).timestamp() if now is None else now
    path=root/'state.json'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    first=not state
    reading=None
    error=None
    try:
        reading=parse_names((read_fn or read_visible_names)())
    except (ValueError,TypeError,KeyError,subprocess.SubprocessError):
        error='source_unavailable_or_invalid'
    previous=state.get('last_sample_epoch')
    state,alerts=evaluate(state,reading,now)
    observed=dt.datetime.fromtimestamp(now,TZ).isoformat()
    if reading is not None:
        stamp=dt.datetime.fromisoformat(reading['timestamp']).timestamp()
        if stamp!=previous:
            record=dict(reading,observed_at=observed,source='Mycodo authenticated live page via Windows UI Automation',fresh=0<=now-stamp<=180,
                        out_of_target={'co2':reading['co2']>=1000,'rh':not 85<=reading['rh']<=90,'temperature':not 22<=reading['temperature']<=28})
            with (root/'readings.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(record,ensure_ascii=False)+'\n')
    state.update(last_tick=observed,last_error=error,device_control_enabled=False)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)
    with (root/'checks.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'checked_at':observed,'source_error':error,'assessment_allowed':state.get('assessment_allowed',False),'alerts':alerts},ensure_ascii=False)+'\n')
    if first:
        if reading is not None and state.get('assessment_allowed'):
            alerts.insert(0,'監控首次讀取成功。資料時間 '+reading['timestamp']+'；CO₂ '+str(reading['co2'])+' ppm，溫度 '+str(reading['temperature'])+'°C，濕度 '+str(reading['rh'])+'% RH。單筆超標會記錄，持續超標才觸發通知。')
        else:
            alerts.insert(0,'監控檢查已啟動，但目前沒有可用的新鮮資料；不能宣稱環境正常。請保持Chrome的Mycodo即時頁開啟及登入。')
    if alerts:
        with (root/'alerts.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':observed,'messages':alerts,'delivery_status':'local_only_telegram_not_connected','within_notification_window':notification_allowed(now)},ensure_ascii=False)+'\n')
        if not notification_allowed(now): return ''
        return '【秀珍菇環境監控｜唯讀、不控制設備】\n'+'\n'.join(alerts)
    return ''

if __name__=='__main__':
    import sys,msvcrt
    sys.stdout.reconfigure(encoding='utf-8')
    runtime=ROOT/'runtime'
    runtime.mkdir(exist_ok=True)
    with (runtime/'tick.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1): lock.write(b'0'); lock.flush()
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: sys.exit(0)
        try:
            message=tick(runtime)
            if message: print(message)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
