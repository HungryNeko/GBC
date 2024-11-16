from fastai.core import *
from fastai.vision import *
from matplotlib.axes import Axes
from filters import IFilter, MasterFilter, ColorizerFilter
from generators import gen_inference_deep, gen_inference_wide
from PIL import Image
import ffmpeg
import yt_dlp as youtube_dl
import gc
import requests
from io import BytesIO
import base64
from IPython import display as ipythondisplay
from IPython.display import HTML
from IPython.display import Image as ipythonimage
import cv2
import logging

# adapted from https://www.pyimagesearch.com/2016/04/25/watermarking-images-with-opencv-and-python/
def get_watermarked(pil_image: Image) -> Image:
    return pil_image


class ModelImageVisualizer:
    def __init__(self, filter: IFilter, results_dir: str = None):
        self.filter = filter
        self.results_dir = None if results_dir is None else Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _clean_mem(self):
        torch.cuda.empty_cache()
        # gc.collect()

    def _open_pil_image(self, path: Path) -> Image:
        return PIL.Image.open(path).convert('RGB')

    def _get_image_from_url(self, url: str) -> Image:
        response = requests.get(url, timeout=30, headers={'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.94 Safari/537.36'})
        img = PIL.Image.open(BytesIO(response.content)).convert('RGB')
        return img

    def plot_transformed_image_from_url(
        self,
        url: str,
        path: str = 'test_images/image.png',
        results_dir:Path = None,
        figsize: Tuple[int, int] = (20, 20),
        render_factor: int = None,
        
        display_render_factor: bool = False,
        compare: bool = False,
        post_process: bool = True,
        watermarked: bool = True,
    ) -> Path:
        img = self._get_image_from_url(url)
        img.save(path)
        return self.plot_transformed_image(
            path=path,
            results_dir=results_dir,
            figsize=figsize,
            render_factor=render_factor,
            display_render_factor=display_render_factor,
            compare=compare,
            post_process = post_process,
            watermarked=watermarked,
        )

    def plot_transformed_image(
        self,
        path: str,
        results_dir:Path = None,
        figsize: Tuple[int, int] = (20, 20),
        render_factor: int = None,
        display_render_factor: bool = False,
        compare: bool = False,
        post_process: bool = True,
        watermarked: bool = True,
    ) -> Path:
        path = Path(path)
        if results_dir is None:
            results_dir = Path(self.results_dir)
        result = self.get_transformed_image(
            path, render_factor, post_process=post_process,watermarked=watermarked
        )
        orig = self._open_pil_image(path)
        if compare:
            self._plot_comparison(
                figsize, render_factor, display_render_factor, orig, result
            )
        else:
            self._plot_solo(figsize, render_factor, display_render_factor, result)

        orig.close()
        result_path = self._save_result_image(path, result, results_dir=results_dir)
        result.close()
        return result_path

    def _plot_comparison(
        self,
        figsize: Tuple[int, int],
        render_factor: int,
        display_render_factor: bool,
        orig: Image,
        result: Image,
    ):
        fig, axes = plt.subplots(1, 2, figsize=figsize)
        self._plot_image(
            orig,
            axes=axes[0],
            figsize=figsize,
            render_factor=render_factor,
            display_render_factor=False,
        )
        self._plot_image(
            result,
            axes=axes[1],
            figsize=figsize,
            render_factor=render_factor,
            display_render_factor=display_render_factor,
        )

    def _plot_solo(
        self,
        figsize: Tuple[int, int],
        render_factor: int,
        display_render_factor: bool,
        result: Image,
    ):
        fig, axes = plt.subplots(1, 1, figsize=figsize)
        self._plot_image(
            result,
            axes=axes,
            figsize=figsize,
            render_factor=render_factor,
            display_render_factor=display_render_factor,
        )

    def _save_result_image(self, source_path: Path, image: Image, results_dir = None) -> Path:
        if results_dir is None:
            results_dir = Path(self.results_dir)
        result_path = results_dir / source_path.name
        image.save(result_path)
        return result_path

    def get_transformed_image(
        self, path: Path, render_factor: int = None, post_process: bool = True,
        watermarked: bool = True,
    ) -> Image:
        self._clean_mem()
        orig_image = self._open_pil_image(path)
        filtered_image = self.filter.filter(
            orig_image, orig_image, render_factor=render_factor,post_process=post_process
        )

        if watermarked:
            return get_watermarked(filtered_image)

        return filtered_image

    def _plot_image(
        self,
        image: Image,
        render_factor: int,
        axes: Axes = None,
        figsize=(20, 20),
        display_render_factor = False,
    ):
        if axes is None:
            _, axes = plt.subplots(figsize=figsize)
        axes.imshow(np.asarray(image) / 255)
        axes.axis('off')
        if render_factor is not None and display_render_factor:
            plt.text(
                10,
                10,
                'render_factor: ' + str(render_factor),
                color='white',
                backgroundcolor='black',
            )

    def _get_num_rows_columns(self, num_images: int, max_columns: int) -> Tuple[int, int]:
        columns = min(num_images, max_columns)
        rows = num_images // columns
        rows = rows if rows * columns == num_images else rows + 1
        return rows, columns


class VideoColorizer:
    def __init__(self, vis: ModelImageVisualizer):
        self.vis = vis
        workfolder = Path('./')
        self.source_folder = workfolder / ""
        self.bwframes_root = workfolder / "bwframes"
        self.audio_root = workfolder / "audio"
        self.colorframes_root = workfolder / "colorframes"
        self.result_folder = workfolder / "result"

    def _purge_images(self, dir):
        for f in os.listdir(dir):
            if re.search('.*?\.jpg', f):
                os.remove(os.path.join(dir, f))

    def _get_ffmpeg_probe(self, path:Path):
        try:
            probe = ffmpeg.probe(str(path))
            return probe
        except ffmpeg.Error as e:
            logging.error("ffmpeg error: {0}".format(e), exc_info=True)
            logging.error('stdout:' + e.stdout.decode('UTF-8'))
            logging.error('stderr:' + e.stderr.decode('UTF-8'))
            raise e
        except Exception as e:
            logging.error('Failed to instantiate ffmpeg.probe.  Details: {0}'.format(e), exc_info=True)   
            raise e

    def _get_fps(self, source_path: Path) -> str:
        probe = self._get_ffmpeg_probe(source_path)
        stream_data = next(
            (stream for stream in probe['streams'] if stream['codec_type'] == 'video'),
            None,
        )
        return stream_data['avg_frame_rate']

    def _download_video_from_url(self, source_url, source_path: Path):
        if source_path.exists():
            source_path.unlink()

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4',
            'outtmpl': str(source_path),
            'retries': 30,
            'fragment-retries': 30
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([source_url])

    def _extract_raw_frames(self, source_path: Path):
        bwframes_folder = self.bwframes_root / (source_path.stem)
        bwframe_path_template = str(bwframes_folder / '%5d.jpg')
        bwframes_folder.mkdir(parents=True, exist_ok=True)
        self._purge_images(bwframes_folder)

        process = (
            ffmpeg
                .input(str(source_path))
                .output(str(bwframe_path_template), format='image2', vcodec='mjpeg', **{'q:v':'0'})
                .global_args('-hide_banner')
                .global_args('-nostats')
                .global_args('-loglevel', 'error')
        )

        try:
            process.run()
        except ffmpeg.Error as e:
            logging.error("ffmpeg error: {0}".format(e), exc_info=True)
            logging.error('stdout:' + e.stdout.decode('UTF-8'))
            logging.error('stderr:' + e.stderr.decode('UTF-8'))
            raise e
        except Exception as e:
            logging.error('Errror while extracting raw frames from source video.  Details: {0}'.format(e), exc_info=True)   
            raise e

    # def _colorize_raw_frames(
    #     self, source_path: Path, render_factor: int = None, post_process: bool = True,
    #     watermarked: bool = False,
    # ):
    #     colorframes_folder = self.colorframes_root / (source_path.stem)
    #     colorframes_folder.mkdir(parents=True, exist_ok=True)
    #     self._purge_images(colorframes_folder)
    #     bwframes_folder = self.bwframes_root / (source_path.stem)
    #
    #     for img in progress_bar(os.listdir(str(bwframes_folder))):
    #         img_path = bwframes_folder / img
    #
    #         if os.path.isfile(str(img_path)):
    #             color_image = self.vis.get_transformed_image(
    #                 str(img_path), render_factor=render_factor, post_process=post_process,watermarked=watermarked
    #             )
    #             color_image.save(str(colorframes_folder / img))
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    import os

    def _colorize_raw_frames(
            self, source_path: Path, render_factor: int = None, post_process: bool = True,
            watermarked: bool = False,
    ):
        colorframes_folder = self.colorframes_root / (source_path.stem)
        colorframes_folder.mkdir(parents=True, exist_ok=True)
        self._purge_images(colorframes_folder)
        bwframes_folder = self.bwframes_root / (source_path.stem)
        image_folder = Path(str(source_path).split(".")[0])  # Convert the split string to a Path
        data_folder=Path("data") / image_folder /"color_images"
        os.makedirs(data_folder, exist_ok=True)
        image_folder = Path("data") / image_folder / "images"  # Use `/` for path joining
        print(image_folder)

        # The rest of your code remains the same
        img_list = os.listdir(image_folder)
        print(img_list)
        mid_point = len(img_list) // 2

        # 前一部分倒着处理
        first_half = img_list[:mid_point][::-1]
        # 后一部分正着处理
        second_half = img_list[mid_point:]

        def process_images(images, reverse=False):
            for img in images:
                img_path = image_folder / img
                if os.path.isfile(str(img_path)):
                    color_image = self.vis.get_transformed_image(
                        str(img_path), render_factor=render_factor, post_process=post_process, watermarked=watermarked
                    )
                    color_image.save(str(data_folder / img))

        # 使用ThreadPoolExecutor创建线程
        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(process_images, first_half, True)
            executor.submit(process_images, second_half, False)

    def _build_video(self, source_path: Path) -> Path:
        pass
        # colorized_path = self.result_folder / (
        #     source_path.name.replace('.mp4', '_no_audio.mp4')
        # )
        # colorframes_folder = self.colorframes_root / (source_path.stem)
        # colorframes_path_template = str(colorframes_folder / '%5d.jpg')
        # colorized_path.parent.mkdir(parents=True, exist_ok=True)
        # if colorized_path.exists():
        #     colorized_path.unlink()
        # fps = self._get_fps(source_path)
        #
        # process = (
        #     ffmpeg
        #         .input(str(colorframes_path_template), format='image2', vcodec='mjpeg', framerate=fps)
        #         .output(str(colorized_path), crf=17, vcodec='libx264')
        #         .global_args('-hide_banner')
        #         .global_args('-nostats')
        #         .global_args('-loglevel', 'error')
        # )
        #
        # try:
        #     process.run()
        # except ffmpeg.Error as e:
        #     logging.error("ffmpeg error: {0}".format(e), exc_info=True)
        #     logging.error('stdout:' + e.stdout.decode('UTF-8'))
        #     logging.error('stderr:' + e.stderr.decode('UTF-8'))
        #     raise e
        # except Exception as e:
        #     logging.error('Errror while building output video.  Details: {0}'.format(e), exc_info=True)
        #     raise e
        #
        # result_path = self.result_folder / source_path.name
        # if result_path.exists():
        #     result_path.unlink()
        # # making copy of non-audio version in case adding back audio doesn't apply or fails.
        # shutil.copyfile(str(colorized_path), str(result_path))
        #
        # # adding back sound here
        # audio_file = Path(str(source_path).replace('.mp4', '.aac'))
        # if audio_file.exists():
        #     audio_file.unlink()
        #
        # os.system(
        #     'ffmpeg -y -i "'
        #     + str(source_path)
        #     + '" -vn -acodec copy "'
        #     + str(audio_file)
        #     + '"'
        #     + ' -hide_banner'
        #     + ' -nostats'
        #     + ' -loglevel error'
        # )
        #
        # if audio_file.exists():
        #     os.system(
        #         'ffmpeg -y -i "'
        #         + str(colorized_path)
        #         + '" -i "'
        #         + str(audio_file)
        #         + '" -shortest -c:v copy -c:a aac -b:a 256k "'
        #         + str(result_path)
        #         + '"'
        #         + ' -hide_banner'
        #         + ' -nostats'
        #         + ' -loglevel error'
        #     )
        # logging.info('Video created here: ' + str(result_path))
        # return result_path

    def colorize_from_url(
        self,
        source_url,
        file_name: str,
        render_factor: int = None,
        post_process: bool = True,
        watermarked: bool = True,

    ) -> Path:
        source_path = self.source_folder / file_name
        self._download_video_from_url(source_url, source_path)
        return self._colorize_from_path(
            source_path, render_factor=render_factor, post_process=post_process,watermarked=watermarked
        )

    def colorize_from_file_name(
        self, file_name: str, render_factor: int = None,  watermarked: bool = False, post_process: bool = True,
    ) -> Path:
        source_path = self.source_folder / file_name
        return self._colorize_from_path(
            source_path, render_factor=render_factor,  post_process=post_process,watermarked=watermarked
        )

    def _colorize_from_path(
        self, source_path: Path, render_factor: int = None,  watermarked: bool = False, post_process: bool = True
    ) -> Path:
        # if not source_path.exists():
        #     raise Exception(
        #         'Video at path specfied, ' + str(source_path) + ' could not be found.'
        #     )
        #self._extract_raw_frames(source_path)
        self._colorize_raw_frames(
            source_path, render_factor=render_factor,post_process=post_process,watermarked=watermarked
        )
        return self._build_video(source_path)


def get_video_colorizer(render_factor: int = 21) -> VideoColorizer:
    return get_stable_video_colorizer(render_factor=render_factor)


def get_artistic_video_colorizer(
    root_folder: Path = Path('./'),
    weights_name: str = 'ColorizeArtistic_gen',
    results_dir='result_images',
    render_factor: int = 35
) -> VideoColorizer:
    learn = gen_inference_deep(root_folder=root_folder, weights_name=weights_name)
    filtr = MasterFilter([ColorizerFilter(learn=learn)], render_factor=render_factor)
    vis = ModelImageVisualizer(filtr, results_dir=results_dir)
    return VideoColorizer(vis)


def get_stable_video_colorizer(
    root_folder: Path = Path('./'),
    weights_name: str = 'ColorizeVideo_gen',
    results_dir='result_images',
    render_factor: int = 21
) -> VideoColorizer:
    learn = gen_inference_wide(root_folder=root_folder, weights_name=weights_name)
    filtr = MasterFilter([ColorizerFilter(learn=learn)], render_factor=render_factor)
    vis = ModelImageVisualizer(filtr, results_dir=results_dir)
    return VideoColorizer(vis)


def get_image_colorizer(
    root_folder: Path = Path('./'), render_factor: int = 35, artistic: bool = True
) -> ModelImageVisualizer:
    if artistic:
        return get_artistic_image_colorizer(root_folder=root_folder, render_factor=render_factor)
    else:
        return get_stable_image_colorizer(root_folder=root_folder, render_factor=render_factor)


def get_stable_image_colorizer(
    root_folder: Path = Path('./'),
    weights_name: str = 'ColorizeStable_gen',
    results_dir='result_images',
    render_factor: int = 35
) -> ModelImageVisualizer:
    learn = gen_inference_wide(root_folder=root_folder, weights_name=weights_name)
    filtr = MasterFilter([ColorizerFilter(learn=learn)], render_factor=render_factor)
    vis = ModelImageVisualizer(filtr, results_dir=results_dir)
    return vis


def get_artistic_image_colorizer(
    root_folder: Path = Path('./'),
    weights_name: str = 'ColorizeArtistic_gen',
    results_dir='result_images',
    render_factor: int = 35
) -> ModelImageVisualizer:
    learn = gen_inference_deep(root_folder=root_folder, weights_name=weights_name)
    filtr = MasterFilter([ColorizerFilter(learn=learn)], render_factor=render_factor)
    vis = ModelImageVisualizer(filtr, results_dir=results_dir)
    return vis


def show_image_in_notebook(image_path: Path):
    ipythondisplay.display(ipythonimage(str(image_path)))


def show_video_in_notebook(video_path: Path):
    video = io.open(video_path, 'r+b').read()
    encoded = base64.b64encode(video)
    ipythondisplay.display(
        HTML(
            data='''<video alt="test" autoplay 
                loop controls style="height: 400px;">
                <source src="data:video/mp4;base64,{0}" type="video/mp4" />
             </video>'''.format(
                encoded.decode('ascii')
            )
        )
    )

from pathlib import Path
import os

def colorize_frames_from_folder(
    bwframes_folder: str, colorframes_folder: str, 
    render_factor: int = None, post_process: bool = True, 
    watermarked: bool = False, max_workers: int = 2
):
    """
    This function colorizes all black and white frames in the specified folder and saves them to another folder.

    Parameters:
    bwframes_folder (str): The folder path containing black and white frames.
    colorframes_folder (str): The folder path where colorized frames will be saved.
    render_factor (int): The render factor to be used during the colorization process (higher = better color).
    post_process (bool): Whether to apply post-processing to colorized images.
    watermarked (bool): Whether to add a watermark to the colorized images.
    max_workers (int): The number of threads to use for parallel processing.
    """
    bwframes_folder = Path(bwframes_folder)
    colorframes_folder = Path(colorframes_folder)
    colorframes_folder.mkdir(parents=True, exist_ok=True)

    img_list = sorted(os.listdir(bwframes_folder))
    mid_point = len(img_list) // 2

    first_half = img_list[:mid_point][::-1]
    second_half = img_list[mid_point:]

    def process_images(images, reverse=False):
        for img in images:
            img_path = bwframes_folder / img
            if os.path.isfile(str(img_path)):
                color_image = video_colorizer.vis.get_transformed_image(
                    str(img_path), render_factor=render_factor, post_process=post_process, watermarked=watermarked
                )
                color_image.save(str(colorframes_folder / img))

    # 使用ThreadPoolExecutor来并行处理图片
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.submit(process_images, first_half, True)
        executor.submit(process_images, second_half, False)



