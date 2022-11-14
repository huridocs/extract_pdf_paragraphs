import ast
from os.path import join

import lightgbm as lgb
import string
from collections import Counter
from typing import List, Tuple, Dict

from huggingface_hub import hf_hub_download
from numpy import unique

from ServiceConfig import ServiceConfig
from extract_pdf_paragraphs.PdfFeatures.PdfFeatures import PdfFeatures
from extract_pdf_paragraphs.PdfFeatures.PdfTag import PdfTag
from extract_pdf_paragraphs.tag_type_finder.LightGBM_30Features_OneHotOneLetter import LightGBM_30Features_OneHotOneLetter


def get_model_configs(config_path: str) -> Dict:
    model_configs: {}
    with open(config_path, "r") as config_file:
        config_contents = config_file.read()
        model_configs = ast.literal_eval(config_contents)
    return model_configs


class PdfAltoXml:
    def __init__(self, pdf_features: PdfFeatures, tag_types: Dict[str, str] = None):
        self.pdf_features = pdf_features
        self.tuples_to_check: List[Tuple[PdfTag, PdfTag]] = list()

        self.lines_space_mode: float = 0
        self.right_space_mode: float = 0
        self.font_size_mode: float = 0

        self.service_config = ServiceConfig()

        if tag_types == None:
            tag_type_finding_config_path = hf_hub_download(
                repo_id="HURIDOCS/pdf_segmetation",
                filename="tag_type_finding_model_config.txt",
                revision="7d98776dd34acb2fe3a06495c82e64b9c84bdc16",
                cache_dir=self.service_config.huggingface_path,
            )

            model_configs: {} = get_model_configs(tag_type_finding_config_path)
            model_path = hf_hub_download(
                repo_id="HURIDOCS/pdf_segmetation",
                filename="tag_type_finding_model.txt",
                revision="c9e886597823a7995a1454f2de43b821bc930368",
                cache_dir=self.service_config.huggingface_path,
            )

            self.tag_type_model = lgb.Booster(model_file=model_path)
            self.tag_type_finder = LightGBM_30Features_OneHotOneLetter([], [], model_configs, self.tag_type_model)
            self.tag_types: Dict[str, str] = self.tag_type_finder.predict(self.pdf_features)
        else:
            self.tag_types: Dict[str, str] = tag_types
        self.letter_corpus: Dict[str, int] = dict()

        letter_corpus_path = hf_hub_download(
            repo_id="HURIDOCS/pdf_segmetation",
            filename="letter_corpus.txt",
            revision="da00a69c8d6a84493712e819580c0148757f466c",
            cache_dir=self.service_config.huggingface_path,
        )

        with open(letter_corpus_path, "r") as corpus_file:
            corpus_contents = corpus_file.read()
            self.letter_corpus = ast.literal_eval(corpus_contents)

        self.len_letter_corpus = len(unique(list(self.letter_corpus.values())))

        self.get_modes()
        self.get_mode_font()

    def get_modes(self):
        line_spaces, right_spaces, left_spaces = [0], [0], [0]

        for page in self.pdf_features.pages:
            for tag in page.tags:
                top, height = tag.bounding_box.top, tag.bounding_box.height
                left, width = tag.bounding_box.left, tag.bounding_box.width
                bottom, right = tag.bounding_box.bottom, tag.bounding_box.right

                on_the_bottom = list(filter(lambda x: bottom < x.bounding_box.top, page.tags))

                if len(on_the_bottom) > 0:
                    line_spaces.append(min(map(lambda x: int(x.bounding_box.top - bottom), on_the_bottom)))

                same_line_tags = filter(
                    lambda x: (top <= x.bounding_box.top < bottom) or (top < x.bounding_box.bottom <= bottom), page.tags
                )
                on_the_right = filter(lambda x: right < x.bounding_box.left, same_line_tags)
                on_the_left = filter(lambda x: x.bounding_box.left < left, same_line_tags)

                if len(list(on_the_right)) == 0:
                    right_spaces.append(int(right))

                if len(list(on_the_left)) == 0:
                    left_spaces.append(int(left))

        self.lines_space_mode = max(set(line_spaces), key=line_spaces.count)
        self.right_space_mode = int(self.pdf_features.pages[0].page_width - max(set(right_spaces), key=right_spaces.count))

    def get_mode_font(self):
        fonts_counter: Counter = Counter()
        for page in self.pdf_features.pages:
            for tag in page.tags:
                fonts_counter.update([tag.font.font_id])

        if len(fonts_counter.most_common()) == 0:
            return

        font_mode_id = fonts_counter.most_common()[0][0]
        font_mode_tag = list(filter(lambda x: x.font_id == font_mode_id, self.pdf_features.fonts))
        if len(font_mode_tag) == 1:
            self.font_size_mode: float = float(font_mode_tag[0].font_size)

    def get_features_for_given_tags(self, tag_1: PdfTag, tag_2: PdfTag, tags_for_page):

        top_1 = tag_1.bounding_box.top
        left_1 = tag_1.bounding_box.left
        right_1 = tag_1.bounding_box.right
        height_1 = tag_1.bounding_box.height
        width_1 = tag_1.bounding_box.width

        on_the_right_left_1, on_the_right_right_1 = self.get_on_the_right_block(tag_1, tags_for_page)
        on_the_left_left_1, on_the_left_right_1 = self.get_on_the_left_block(tag_1, tags_for_page)

        right_gap_1 = on_the_right_left_1 - right_1

        top_2 = tag_2.bounding_box.top
        left_2 = tag_2.bounding_box.left
        right_2 = tag_2.bounding_box.right
        height_2 = tag_2.bounding_box.height
        width_2 = tag_2.bounding_box.width

        on_the_right_left_2, on_the_right_right_2 = self.get_on_the_right_block(tag_2, tags_for_page)
        on_the_left_left_2, on_the_left_right_2 = self.get_on_the_left_block(tag_2, tags_for_page)
        left_gap_2 = left_2 - on_the_left_right_2

        absolute_right_1 = max(left_1 + width_1, on_the_right_right_1)
        absolute_right_2 = max(left_2 + width_2, on_the_right_right_2)

        end_lines_difference = abs(absolute_right_1 - absolute_right_2)

        on_the_left_left_1 = left_1 if on_the_left_left_1 == 0 else on_the_left_left_1
        on_the_left_left_2 = left_2 if on_the_left_left_2 == 0 else on_the_left_left_2
        absolute_left_1 = min(left_1, on_the_left_left_1)
        absolute_left_2 = min(left_2, on_the_left_left_2)

        start_lines_differences = absolute_left_1 - absolute_left_2

        tags_in_the_middle = list(filter(lambda x: tag_1.bounding_box.bottom <= x.bounding_box.top < top_2, tags_for_page))
        tags_in_the_middle_top = (
            max(map(lambda x: x.bounding_box.top, tags_in_the_middle)) if len(tags_in_the_middle) > 0 else 0
        )
        tags_in_the_middle_bottom = (
            min(map(lambda x: x.bounding_box.bottom, tags_in_the_middle)) if len(tags_in_the_middle) > 0 else 0
        )

        top_distance = top_2 - top_1 - height_1

        gap_middle_top = tags_in_the_middle_top - top_1 - height_1 if tags_in_the_middle_top > 0 else 0
        gap_middle_bottom = top_2 - tags_in_the_middle_bottom if tags_in_the_middle_bottom > 0 else 0

        top_distance_gaps = top_distance - (gap_middle_bottom - gap_middle_top)

        right_distance = left_2 - left_1 - width_1
        left_distance = left_1 - left_2

        height_difference = height_1 - height_2

        same_font = True if tag_1.font.font_id == tag_2.font.font_id else False

        tag_1_first_letter: List
        tag_1_second_letter: List
        tag_1_last_letter: List
        tag_1_second_last_letter: List
        tag_2_first_letter: List
        tag_2_second_letter: List
        tag_2_last_letter: List
        tag_2_second_last_letter: List

        if tag_1.id == "pad_tag":
            tag_1_type = "pad_type"
            tag_1_first_letter = self.len_letter_corpus * [-1]
            tag_1_second_letter = self.len_letter_corpus * [-1]
            tag_1_last_letter = self.len_letter_corpus * [-1]
            tag_1_second_last_letter = self.len_letter_corpus * [-1]
        else:
            tag_1_type = self.tag_types[tag_1.id]
            tag_1_first_letter = self.len_letter_corpus * [0]
            if tag_1.content[0] in self.letter_corpus.keys():
                tag_1_first_letter[self.letter_corpus[tag_1.content[0]]] = 1
            tag_1_last_letter = self.len_letter_corpus * [0]
            if tag_1.content[-1] in self.letter_corpus.keys():
                tag_1_last_letter[self.letter_corpus[tag_1.content[-1]]] = 1

            if len(tag_1.content) > 1:
                tag_1_second_letter = self.len_letter_corpus * [0]
                if tag_1.content[1] in self.letter_corpus.keys():
                    tag_1_second_letter[self.letter_corpus[tag_1.content[1]]] = 1
                tag_1_second_last_letter = self.len_letter_corpus * [0]
                if tag_1.content[-2] in self.letter_corpus.keys():
                    tag_1_second_last_letter[self.letter_corpus[tag_1.content[-2]]] = 1
            else:
                tag_1_second_letter = self.len_letter_corpus * [-1]
                tag_1_second_last_letter = self.len_letter_corpus * [-1]

        if tag_2.id == "pad_tag":
            tag_2_type = "pad_type"
            tag_2_first_letter = self.len_letter_corpus * [-1]
            tag_2_second_letter = self.len_letter_corpus * [-1]
            tag_2_last_letter = self.len_letter_corpus * [-1]
            tag_2_second_last_letter = self.len_letter_corpus * [-1]
        else:
            tag_2_type = self.tag_types[tag_2.id]
            tag_2_first_letter = self.len_letter_corpus * [0]
            if tag_2.content[0] in self.letter_corpus.keys():
                tag_2_first_letter[self.letter_corpus[tag_2.content[0]]] = 1
            tag_2_last_letter = self.len_letter_corpus * [0]
            if tag_2.content[-1] in self.letter_corpus.keys():
                tag_2_last_letter[self.letter_corpus[tag_2.content[-1]]] = 1

            if len(tag_2.content) > 1:
                tag_2_second_letter = self.len_letter_corpus * [0]
                if tag_2.content[1] in self.letter_corpus.keys():
                    tag_2_second_letter[self.letter_corpus[tag_2.content[1]]] = 1
                tag_2_second_last_letter = self.len_letter_corpus * [0]
                if tag_2.content[-2] in self.letter_corpus.keys():
                    tag_2_second_last_letter[self.letter_corpus[tag_2.content[-2]]] = 1
            else:
                tag_2_second_letter = self.len_letter_corpus * [-1]
                tag_2_second_last_letter = self.len_letter_corpus * [-1]

        features = [
            self.font_size_mode / 100,
            same_font,
            absolute_right_1,
            top_1,
            right_1,
            width_1,
            height_1,
            top_2,
            right_2,
            width_2,
            height_2,
            top_distance,
            top_distance - self.lines_space_mode,
            top_distance_gaps,
            self.lines_space_mode - top_distance_gaps,
            self.right_space_mode - absolute_right_1,
            top_distance - height_1,
            start_lines_differences,
            right_distance,
            left_distance,
            right_gap_1,
            left_gap_2,
            height_difference,
            end_lines_difference,
            tag_1_type == "text",
            tag_1_type == "title",
            tag_1_type == "figure",
            tag_1_type == "table",
            tag_1_type == "list",
            tag_1_type == "footnote",
            tag_1_type == "formula",
            tag_2_type == "text",
            tag_2_type == "title",
            tag_2_type == "figure",
            tag_2_type == "table",
            tag_2_type == "list",
            tag_2_type == "footnote",
            tag_2_type == "formula",
            len(tag_1.content),
            len(tag_2.content),
            tag_1.content.count(" "),
            tag_2.content.count(" "),
            sum(character in string.punctuation for character in tag_1.content),
            sum(character in string.punctuation for character in tag_2.content),
        ]

        features.extend(tag_1_first_letter)
        features.extend(tag_1_second_letter)
        features.extend(tag_1_second_last_letter)
        features.extend(tag_1_last_letter)
        features.extend(tag_2_first_letter)
        features.extend(tag_2_second_letter)
        features.extend(tag_2_second_last_letter)
        features.extend(tag_2_last_letter)

        return features

    @staticmethod
    def get_on_the_right_block(tag: PdfTag, tags: List[PdfTag]):
        top = tag.bounding_box.top
        height = tag.bounding_box.height
        left = tag.bounding_box.left

        on_the_right = list(
            filter(
                lambda x: (top <= x.bounding_box.top < (top + height)) or (top < (x.bounding_box.bottom) <= (top + height)),
                tags,
            )
        )

        on_the_right = list(filter(lambda x: left < x.bounding_box.left, on_the_right))
        on_the_right_left = 0 if len(on_the_right) == 0 else min(map(lambda x: x.bounding_box.left, on_the_right))
        on_the_right_right = 0 if len(on_the_right) == 0 else max(map(lambda x: x.bounding_box.right, on_the_right))

        return on_the_right_left, on_the_right_right

    @staticmethod
    def get_on_the_left_block(tag, tags):
        top = tag.bounding_box.top
        height = tag.bounding_box.height
        right = tag.bounding_box.right

        on_the_left = list(
            filter(
                lambda x: (top <= x.bounding_box.top < (top + height)) or (top < (x.bounding_box.bottom) <= (top + height)),
                tags,
            )
        )

        on_the_left = list(filter(lambda x: x.bounding_box.right < right, on_the_left))
        on_the_left_left = 0 if len(on_the_left) == 0 else min(map(lambda x: x.bounding_box.left, on_the_left))
        on_the_left_right = 0 if len(on_the_left) == 0 else max(map(lambda x: x.bounding_box.right, on_the_left))

        return on_the_left_left, on_the_left_right
