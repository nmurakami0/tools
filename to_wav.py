from pydub import AudioSegment

# MP3ファイルを読み込む
audio = AudioSegment.from_mp3("/Users/murakaminaoya/Downloads/audio.mp3")

# WAVファイルとして書き出す
audio.export("124.wav", format="wav")
