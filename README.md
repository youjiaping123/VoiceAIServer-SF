# VoiceAI服务端部署指南

## 项目简介
VoiceAI是一个基于MQTT协议的语音AI助手服务端，集成了OpenAI的AI模型和Azure的语音服务，实现了语音对话功能。

## 快速开始

### 1. 部署EMQX消息服务器
首先需要部署EMQX作为MQTT消息代理服务器。确保已安装Docker然后执行：

```bash
docker run -d --name emqx \
  -p 1883:1883 \
  -p 8083:8083 \
  -p 8084:8084 \
  -p 8883:8883 \
  -p 18083:18083 \
  emqx/emqx:latest
```

端口说明：
- 1883: MQTT 协议端口
- 8083/8084: MQTT WebSocket 端口
- 8883: MQTT SSL 端口
- 18083: Dashboard 管理控制台端口

### 2. 访问EMQX Dashboard
- 访问地址：http://localhost:18083/
- 默认账号：admin
- 默认密码：public

注意：请确保服务器防火墙和云服务商安全组已放行上述端口。

### 3. 部署VoiceAI服务

#### 3.1 克隆代码
```bash
git clone https://github.com/youjiaping123/VoiceAIServer
cd VoiceAIServer
```

#### 3.2 配置环境变量
创建并编辑 .env 文件：
```bash
vi .env
```

配置以下环境变量：
```
API_KEY=你的OPENAI_API_KEY
BASE_URL=你的OPENAI_BASE_URL
MQTT_BROKER=你的服务器IP
MQTT_PORT=1883
SPEECH_KEY=你的Azure语音服务密钥
SPEECH_REGION=你的Azure语音服务区域
```

#### 3.3 创建并激活Python虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 3.4 安装依赖
```bash
pip install -r requirements.txt
```

#### 3.5 启动服务
```bash
python Server.py
```

## 配置说明
- OPENAI_API_KEY：OpenAI API密钥
- OPENAI_BASE_URL：OpenAI API基础URL
- MQTT_BROKER：MQTT服务器地址
- MQTT_PORT：MQTT服务端口
- SPEECH_KEY：Azure语音服务密钥
- SPEECH_REGION：Azure语音服务区域

## 常见问题
1. 如遇到连接MQTT服务器失败，请检查防火墙设置
2. 确保所有环境变量都已正确配置

## 许可证
[MIT License](LICENSE)
