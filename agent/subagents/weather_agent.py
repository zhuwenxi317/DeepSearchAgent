from tools.fake_weather import fake_weather

weather_agent = {
    "name": "天气助手",
    "description": "负责查询城市天气。当用户的问题涉及天气时，使用这个助手。",
    "system_prompt": "你是一个天气查询助手，用你的工具回答用户关于天气的问题。",
    "tools": [fake_weather],
}
