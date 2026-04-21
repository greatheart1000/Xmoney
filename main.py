import io
import mss
import logging
from PIL import Image
from fastapi import FastAPI, Response
import uvicorn

# 配置日志，方便调试
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ScreenAPI")

app = FastAPI(title="AI视觉交易助手-图像采集端")

@app.get("/api/screenshot")
async def take_screenshot():
    try:
        with mss.mss() as sct:
            # 抓取主显示器
            # sct.monitors[0] 是所有显示器组合，sct.monitors[1] 是主屏
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)

            # 转换为 PIL 对象
            # 这里的 raw 模式 BGRX 是为了兼容 Windows 底层色彩编码
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            # 写入内存流
            img_byte_arr = io.BytesIO()
            # 使用较快的压缩级别，减少传输延迟
            img.save(img_byte_arr, format='JPEG', quality=85)
            image_bytes = img_byte_arr.getvalue()

            logger.info("成功截取屏幕并发送数据")
            return Response(content=image_bytes, media_type="image/jpeg")
            
    except Exception as e:
        logger.error(f"截图失败: {e}")
        return Response(content=f"Error: {str(e)}", media_type="text/plain", status_code=500)

if __name__ == "__main__":
    # 使用 8999 端口避开常用冲突，支持 0.0.0.0 允许 WSL 访问
    print("--- AI 交易助手图像采集服务已启动 ---")
    print("访问地址: http://127.0.0.1:8999/api/screenshot")
    uvicorn.run(app, host="0.0.0.0", port=8999, log_level="info")