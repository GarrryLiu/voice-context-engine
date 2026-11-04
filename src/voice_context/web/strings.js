'use strict';
// Product-only interface translations. User speech, replies and names are untouched.
window.voiceUI=text=>{
 const strings={
 '准备就绪':'Ready when you are','正在连接…':'Connecting…','本地服务已连接':'Connected to local workspace','连接失败':'Connection failed',
 '等待录音…':'Ready to listen…','开始一次对话。':'Start a conversation.','已确认发言，正在生成回复…':'Thought saved. Preparing a reply…',
 '开始连续对话':'Start talking','结束连续对话':'Pause microphone','连续对话已结束':'Microphone paused',
 '正在连接实时转写…':'Connecting your microphone…','连续对话中，可以开始说话':'Listening. Go ahead.',
 '正在听…':'Listening…','正在录音…':'Recording…','正在上传录音…':'Uploading audio…','正在转写':'Transcribing…','正在思考…':'Thinking…','正在播放':'Speaking…',
 '已停止':'Stopped','回复结束，可以继续说':'Reply finished. Ready when you are.',
 '本轮未完成，可重新录音':'That didn’t finish. Try recording again.',
 '播放确认失败，恢复上下文可能缺少回复':'Playback could not be confirmed. This reply may be missing when you return.',
 '本轮未完成，请检查连接或稍后重试。':'That didn’t finish. Check your connection and try again.',
 '实时转写连接超时，请重试':'Connection timed out. Please try again.',
 '实时转写连接失败，请重试':'Could not connect. Please try again.',
 '实时转写连接已结束，请重新开始':'Connection ended. Start a new conversation.',
 '实时转写连接已结束，请重新开始。':'Connection ended. Start a new conversation.',
 '上传积压，已停止麦克风，请重试':'Upload stalled. Microphone stopped. Please try again.',
 '采集积压，已停止麦克风，请重试':'Audio capture stalled. Microphone stopped. Please try again.',
 '实时对话未完成，请重试':'The conversation did not finish. Please try again.',
 '无法启动连续对话，请检查麦克风权限和连接':'Could not start. Check microphone permissions and your connection.',
 '录音超过 2MB，请缩短后重试':'Recording exceeds 2 MB. Try a shorter clip.',
 '录音需小于 2MB':'Audio must be smaller than 2 MB.',
 '连接中断，回复未完成':'Connection lost before the reply finished.',
 '音频采样格式错误':'Unsupported audio sample format.'
 };
 if(Object.hasOwn(strings,text))return strings[text];
 for(const [from,to] of [['已切换到 ','Switched to '],['服务请求失败 (','Request failed ('],['录音请求失败 (','Audio request failed ('],['无法使用麦克风：','Microphone unavailable: ']])if(text.startsWith(from))return to+text.slice(from.length);
 return text;
};
