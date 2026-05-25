module.exports = {
  expo: {
    name: process.env.APP_ENV === "development" 
      ? "ECG Monitor (Dev)" 
      : process.env.APP_ENV === "preview" 
        ? "ECG Monitor (Preview)" 
        : "ECG Monitor",
    slug: "mobile_app",
    version: "1.0.0",
    orientation: "portrait",
    icon: "./assets/icon.png",
    userInterfaceStyle: "light",
    splash: {
      image: "./assets/splash-icon.png",
      resizeMode: "contain",
      backgroundColor: "#f3f7f8"
    },
    ios: {
      supportsTablet: true
    },
    android: {
      adaptiveIcon: {
        backgroundColor: "#f3f7f8",
        foregroundImage: "./assets/android-icon-foreground.png",
        backgroundImage: "./assets/android-icon-background.png",
        monochromeImage: "./assets/android-icon-monochrome.png"
      },
      permissions: [
        "android.permission.BLUETOOTH",
        "android.permission.BLUETOOTH_ADMIN",
        "android.permission.BLUETOOTH_CONNECT"
      ],
      package: process.env.APP_ENV === "development" 
        ? "com.anonymous.mobile_app.dev" 
        : process.env.APP_ENV === "preview"
          ? "com.anonymous.mobile_app.preview"
          : "com.anonymous.mobile_app"
    },
    web: {
      favicon: "./assets/favicon.png"
    },
    plugins: [
      [
        "react-native-ble-plx",
        {
          "isBackgroundEnabled": true,
          "modes": [
            "peripheral",
            "central"
          ],
          "bluetoothAlwaysPermission": "Allow $(PRODUCT_NAME) to connect to bluetooth devices"
        }
      ]
    ],
    extra: {
      eas: {
        projectId: "2cbfa8c6-82e0-4ca4-8802-01f66549a43e"
      }
    },
    owner: "kevin559009390"
  }
};
