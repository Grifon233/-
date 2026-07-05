import os

ANDROID_CLIENT_ID = os.getenv(
    "HH_ANDROID_CLIENT_ID",
    "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD"
)

ANDROID_CLIENT_SECRET = os.getenv(
    "HH_ANDROID_CLIENT_SECRET",
    "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS"
)

# Используется для прямой авторизации. Этот способ мной не используется, так как
# для отображения капчи все равно нужен webview.

