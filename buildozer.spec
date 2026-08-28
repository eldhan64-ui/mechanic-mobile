[app]
title = Mechanic Mobile
package.name = mechanicmobile
package.domain = org.workshop
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,db,txt
version = 1.0.0
requirements = python3,kivy,plyer
orientation = portrait
fullscreen = 0
android.permissions = CAMERA,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

[buildozer]
log_level = 2
warn_on_root = 1

[android]
android.api = 31
android.minapi = 23
android.archs = arm64-v8a,armeabi-v7a
android.accept_sdk_license = True
android.ndk_api = 23
