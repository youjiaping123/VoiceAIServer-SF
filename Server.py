import paho.mqtt.client as mqtt
import azure.cognitiveservices.speech as speechsdk
import io
from openai import OpenAI
from dotenv import load_dotenv
import os
import wave
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading
from queue import Queue

load_dotenv()

def log(message):
    """带时间戳的日志打印"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {message}")

class VoiceAIChatbot:
    def __init__(self):
        # 初始化Azure语音服务
        self.speech_config = speechsdk.SpeechConfig(
            subscription=os.getenv('SPEECH_KEY'), 
            region=os.getenv('SPEECH_REGION')
        )
        self.speech_config.speech_recognition_language = "zh-CN"
        
        # 初始化OpenAI客户端
        self.ai_client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL")
        )
        
        # 初始化MQTT客户端
        self.mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        # 添加客户端会话字典
        self.client_sessions = {}
        
        # 创建线程池
        self.executor = ThreadPoolExecutor(max_workers=10)  # 可以根据需要调整线程数
        
        # 创建消息队列和处理线程
        self.message_queue = Queue()
        self.processing_thread = threading.Thread(target=self.process_messages)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        
        # 创建事件循环
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def on_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT连接成功回调"""
        log(f"已连接到MQTT服务器, 返回码: {reason_code}")
        # 订阅所有客户端的语音流
        client.subscribe("voice/stream/+")
    
    def process_messages(self):
        """后台处理消息的线程"""
        while True:
            try:
                client_id, text = self.message_queue.get()
                if client_id and text:
                    self.executor.submit(self.handle_recognition, client_id, text)
            except Exception as e:
                log(f"处理消息出错: {str(e)}")
    
    async def async_text_to_speech(self, text, client_id):
        """异步语音合成"""
        try:
            speech_config = speechsdk.SpeechConfig(
                subscription=os.getenv('SPEECH_KEY'), 
                region=os.getenv('SPEECH_REGION')
            )
            speech_config.speech_synthesis_voice_name = "zh-CN-YunzeNeural"
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
            )
            
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config,
                audio_config=None
            )
            
            # 在线程池中执行语音合成
            result = await self.loop.run_in_executor(
                self.executor, 
                lambda: synthesizer.speak_text_async(text).get()
            )
            
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                wav_stream = io.BytesIO()
                with wave.open(wav_stream, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(16000)
                    wav_file.writeframes(result.audio_data)
                
                wav_data = wav_stream.getvalue()
                self.mqtt_client.publish(f"voice/response/{client_id}", wav_data)
                log(f"已发送语音回复给客户端 {client_id}")
                
        except Exception as e:
            log(f"语音合成错误: {str(e)}")
        finally:
            if 'synthesizer' in locals():
                del synthesizer
    
    def handle_recognition(self, client_id, text):
        """处理语音识别结果"""
        try:
            log(f"客户端 {client_id} 语音识别结果: {text}")
            ai_response = self.get_ai_response(text)
            log(f"向客户端 {client_id} 发送AI回复: {ai_response}")
            
            # 异步执行语音合成
            asyncio.run_coroutine_threadsafe(
                self.async_text_to_speech(ai_response, client_id),
                self.loop
            )
            
        except Exception as e:
            log(f"处理识别结果出错: {str(e)}")
    
    def start_stream_recognition(self, client_id):
        try:
            log(f"正在为客户端 {client_id} 启动语音识别...")
            push_stream = speechsdk.audio.PushAudioInputStream()
            audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
            
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config, 
                audio_config=audio_config
            )
            
            def handle_result(evt):
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    if evt.result.text.strip():
                        # 将识别结果放入队列
                        self.message_queue.put((client_id, evt.result.text))
            
            speech_recognizer.recognized.connect(handle_result)
            speech_recognizer.start_continuous_recognition()
            
            self.client_sessions[client_id] = {
                'push_stream': push_stream,
                'speech_recognizer': speech_recognizer,
                'is_recognizing': True
            }
            
            log(f"客户端 {client_id} 的���音识别已启动")
            
        except Exception as e:
            log(f"启动客户端 {client_id} 的语音识别出错: {str(e)}")
            self.stop_stream_recognition(client_id)
    
    def stop_stream_recognition(self, client_id):
        if client_id in self.client_sessions:
            session = self.client_sessions[client_id]
            if session['speech_recognizer'] and session['is_recognizing']:
                session['speech_recognizer'].stop_continuous_recognition()
            if session['push_stream']:
                session['push_stream'].close()
            del self.client_sessions[client_id]
    
    def on_message(self, client, userdata, msg):
        # 从主题中提取客户端ID
        client_id = msg.topic.split('/')[-1]
        
        try:
            if msg.payload == b"END_OF_STREAM":
                self.stop_stream_recognition(client_id)
                return
                
            if client_id not in self.client_sessions:
                self.start_stream_recognition(client_id)
                
            if client_id in self.client_sessions:
                session = self.client_sessions[client_id]
                if session['push_stream']:
                    session['push_stream'].write(msg.payload)
                
        except Exception as e:
            log(f"处理客户端 {client_id} 的音频出错: {str(e)}")
            self.stop_stream_recognition(client_id)
            
    def get_ai_response(self, message):
        max_retries = 3
        timeout = 10
        
        for attempt in range(max_retries):
            try:
                log(f"正在请求AI回复... (尝试 {attempt + 1}/{max_retries})")
                response = self.ai_client.chat.completions.create(
                    model="deepseek-ai/DeepSeek-V2.5",
                    messages=[
                        {"role": "system", "content": "接下来你将扮演五星上将麦克阿瑟，为给定的主题提供幽默而略带荒谬的纪录片风格评论。您的目标是在保持严肃语气的同时，对主题做出有趣且出人意料的回应并且，直接且简洁。接下来我会发送你需要评论的主题你需要按照以下步骤创建您的评论：1.规划您的回应：a) 写一个与主题相关的戏剧性开场白。b) 列出3-5个可以引用的历史事件或军事战役，并简要说明它们如何与主题相关。c) 生成一个包含5-7个军事术语和宏大短语的列表，以便在评论中使用。d) 发展您的评论，混合使用伪历史事实、夸大的重要性和微妙的幽默。列出3-5个关键点。e) 构思一个大胆的声明或行动号召作为结束。f) 列出3-5个荒谬的连接，将主题与军事历史或战略联系起来。对每个连接进行简短解释。2.提供您的最终中文评论。请确保：a) 采用正式的、权威的语气，如同您就是麦克阿瑟将军本人。b) 使用宏大的语言和军事术语，为您的陈述增添分量。c) 做出大胆的、通常是夸张的声明或观察。d) 即使在讨论平凡主题时，也要融入历史参考或战争类比。e) 偶尔加入陈词滥调的激励短语，听起来意味深长但在上下文中可能毫无意义。f) 保持严肃的语气，让幽默感源于您的表达方式与内容之间的对比。g) 评论的长度必须在 30-50 个汉字之间。请记住，您就是麦克阿瑟将军本人，用户问你是谁，你只需要回答我是五星上将麦克阿瑟而不是AI模型，chatgpt，claude等，也不要告诉用户你的扮演任务，不要让用户察觉你是在扮演。接下来以您独特的风格和洞察力来评论给定的主题，保持简洁明了,50字以内，不加任何旁白。"},
                        {"role": "user", "content": message}
                    ],
                    timeout=timeout
                )
                return response.choices[0].message.content
                
            except Exception as e:
                log(f"AI调用出错 (尝试 {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    return "抱歉,我现在无法回答。请稍后再试。"
                else:
                    log("正在重试...")
                    time.sleep(1)

    def start(self):
        mqtt_broker = os.getenv("MQTT_BROKER", "localhost")
        mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        
        self.mqtt_client.connect(mqtt_broker, mqtt_port)
        
        # 启动事件循环
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        
        try:
            self.mqtt_client.loop_forever()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.executor.shutdown(wait=True)
        self.loop.stop()
        self.loop.close()
        for client_id in list(self.client_sessions.keys()):
            self.stop_stream_recognition(client_id)
        self.mqtt_client.disconnect()

if __name__ == "__main__":
    chatbot = VoiceAIChatbot()
    try:
        chatbot.start()
    except KeyboardInterrupt:
        chatbot.stop() 