import librosa
import numpy as np
import scipy.signal as signal
import noisereduce as nr
import webrtcvad
import wave
import struct
from pydub import AudioSegment

def load_audio(file_path, sr=16000):
    """ MP3 または WAV を読み込んで numpy 配列に変換 """
    if file_path.lower().endswith(".mp3"):
        audio = AudioSegment.from_mp3(file_path)
        audio = audio.set_channels(1).set_frame_rate(sr)  # モノラル化＆サンプリングレート変更
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
    else:
        samples, _ = librosa.load(file_path, sr=sr, mono=True)

    return samples, sr

def noise_reduction(audio, sr):
    """ ノイズ除去 """
    return nr.reduce_noise(y=audio, sr=sr)

def bandpass_filter(audio, sr, lowcut=300, highcut=3400):
    """ バンドパスフィルタで人間の声を強調 """
    nyquist = sr / 2
    b, a = signal.butter(6, [lowcut / nyquist, highcut / nyquist], btype='band')
    return signal.filtfilt(b, a, audio)

def vad_filter(audio, sr, frame_ms=30):
    """ VAD（音声区間検出）で人間の声だけを抽出 """
    vad = webrtcvad.Vad(2)
    frame_size = int(sr * frame_ms / 1000)

    filtered_audio = []
    for i in range(0, len(audio) - frame_size, frame_size):
        frame = audio[i:i+frame_size]
        raw_frame = struct.pack("%dh" % len(frame), *(np.int16(frame * 32768)))

        if vad.is_speech(raw_frame, sr):
            filtered_audio.extend(frame)

    return np.array(filtered_audio)

def save_audio(file_path, audio, sr, format="wav"):
    """ 音声データを WAV または MP3 で保存 """
    audio_segment = AudioSegment(
        (audio * 32768).astype(np.int16).tobytes(),
        frame_rate=sr,
        sample_width=2,
        channels=1
    )

    if format == "mp3":
        audio_segment.export(file_path, format="mp3", bitrate="192k")
    else:
        audio_segment.export(file_path, format="wav")

# 音声処理の実行
input_file = "/Users/murakaminaoya/Downloads/audio.mp3"  # MP3 でも WAV でもOK
output_file = "output.mp3"  # MP3 で出力

audio, sr = load_audio(input_file)
audio = noise_reduction(audio, sr)
audio = bandpass_filter(audio, sr)
audio = vad_filter(audio, sr)
save_audio(output_file, audio, sr, format="mp3")

print(f"処理が完了しました: {output_file}")
