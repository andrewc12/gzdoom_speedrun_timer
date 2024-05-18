#!/usr/bin/env python
"A speedrun timer for gzdoom"
# I avoided using the word "map" for maps and instead called them "levels" since map is a default function in python

import os, json, bz2
from sys import argv
from math import floor
from datetime import datetime, timedelta
from subprocess import Popen, PIPE
from threading import Thread

from PyQt5 import QtWidgets, QtCore, QtGui

from mainwindow import Ui_MainWindow


class WrongChapter(Exception):
    "A Chapter tried to look up one of it's levels by code, but that code corresponds to a different chapter."


class SerializedEmpty(Exception):
    "You tried to serialize a Level or Chapter that has no data to be saved."


class LevelChapter():
    "Base class of both Levels and Chapters."
    def __init__(self, personal_best: timedelta=None):
        """
        name is a str: The normal name of the level or chapter: "Hangar" or "Knee-Deep In The Dead"
        personal_best: Your all-time personal best. This is saved when the program is closed.

        session_time: The current time for this session. This information is discarded when the program is closed.
        self.diff: str that represents the time difference between session_time and personal_best.
        self.modified: bool of whether this object has a new personal_best that needs to be saved.
        """
        self.session_time = None
        self.personal_best = personal_best
        self._set_diff() # sets self.diff
        self.modified = False # indicates whether this level or chapter has a new PB worth saving
        self._orig_pb = personal_best # This is used in case the user reverts back and forth.
        # It allows us to tell if this modified LevelChapter is unmodified again
        self._backup_pb = self._backup_session_time = None # The values we revert to if the user reverts

    def pretty_time(self, delta: timedelta) -> str:
        "Convert timedelta into a pretty string that looks like 02:04.60"
        # a microsecond is 1/1,000,000th of a second, one millionth
        return "".join((str(floor(delta.seconds/60)).zfill(2), ":", str(delta.seconds%60).zfill(2), ".", str(round(delta.microseconds*.0001)).rjust(2, "0")))

    def revert_session_time(self) -> None:
        "Revert the session time to the last time stored."
        self._backup_session_time, self.session_time = self.session_time, self._backup_session_time
        self._set_diff()

    def revert_personal_best(self) -> None:
        "Revert the personal best time to the last time stored."
        self._backup_pb, self.personal_best = self.personal_best, self._backup_pb
        if self.personal_best == self._orig_pb:
            self.modified = False
        else:
            self.modified = True
        self._set_diff()

    def delete_session_time(self) -> None:
        "Delete the session time."
        if self.session_time: # don't back up a blank session time, keep whatever last value was stored.
            self._backup_session_time = self.session_time
            self.session_time = None

    def delete_personal_best(self) -> None:
        "Delete the personal best time."
        if self.personal_best:
            self._backup_pb = self.personal_best
            self.personal_best = None

    def _set_diff(self) -> None:
        "helper method to set self.diff as the difference between session_time and personal_best"
        if self.session_time is None or self.personal_best is None:
            self.diff = None
            return
        if self.session_time < self.personal_best:
            symbol = "-"
            diff_time = self.personal_best - self.session_time
        else:
            symbol = "+"
            diff_time = self.session_time - self.personal_best
        self.diff = f"{symbol}{self.pretty_time(diff_time)}"

    def _is_session_pb(self) -> bool:
        "Helper method to check if this object's session_time is a personal_best."
        if self.personal_best is None or self.session_time < self.personal_best:
            self._backup_pb = self.personal_best
            self.personal_best = self.session_time
            self.modified = True
            return True
        return False


class Level(LevelChapter):
    "A single doom level."
    _doom1_secret_exits = (3, 5, 6, 2) # level numbers used to set flags upon level creation
    _level_names = [['Hangar', # index 0 is chapter 1
                    'Nuclear Plant',
                    'Toxin Refinery',
                    'Command Control',
                    'Phobos Lab',
                    'Central Processing',
                    'Computer Station',
                    'Phobos Anomaly',
                    'Military Base'],
                    ['Deimos Anomaly', # chapter 2
                    'Containment Area',
                    'Refinery',
                    'Deimos Lab',
                    'Command Center',
                    'Halls of The Damned',
                    'Spawning Vats',
                    'Tower of Babel',
                    'Fortress of Mystery'],
                    ['Hell Keep', # chapter 3
                    'Slough of Despair',
                    'Pandemonium',
                    'House of Pain',
                    'Unholy Cathedral',
                    'Mt. Erebus',
                    'Limbo', # shown as "Gate To Limbo" on the score screen
                    'Dis',
                    'Warrens'],
                    ['Hell Beneath', # chapter 4
                    'Perfect Hatred',
                    'Sever the Wicked',
                    'Unruly Evil',
                    'They Will Repent',
                    'Against Thee Wickedly',
                    'And Hell Followed',
                    'Unto the Cruel',
                    'Fear'],
                    ['Entryway', # chapter 5 is Doom2
                    'Underhalls',
                    'The Gantlet',
                    'The Focus',
                    'The Waste Tunnels',
                    'The Crusher',
                    'Dead Simple',
                    'Tricks and Traps',
                    'The Pit',
                    'Refueling Base',
                    '"O" of Destruction!', # doom calls it this while the title screen calls it "Circle of Death"
                    'The Factory',
                    'Downtown',
                    'The Inmost Dens',
                    'Industrial Zone',
                    'Suburbs',
                    'Tenements',
                    'The Courtyard',
                    'The Citadel',
                    'Gotcha!',
                    'Nirvana',
                    'The Catacombs',
                    "Barrels o' Fun",
                    'The Chasm',
                    'Bloodfalls',
                    'The Abandoned Mines',
                    'Monster Condo',
                    'The Spirit World',
                    'The Living End',
                    'Icon of Sin',
                    'Wolfenstein',
                    'Grosse']]

    def __init__(self, code: str, personal_best: timedelta=None):
        """
        code is the few character short code that the game uses, the very first is E1M1
            Chapters 1-4 stop at 9 so there is no 0 padding.
            Doom 2 uses a different format: MAP01 with 0 padding and goes to 32.

        self.name str: the title that the game uses, for example the first is Hangar.
        self.secret_exit str: if the level has an exit to a secret level, this value is the code of the destination secret level.
        self.secret str: if this level is a secret level, this value is the code of the destination level.
        self.chapter_name str: the chapter this level belongs to.
        self.chapter_number int: this level's chapter number. Doom2 is 5.
        self.level_number int: this level's number.
        self.final bool: whether or not this level is the final level in the chapter.
        self.modified bool: whether or not this level's personal_best needs to be saved.
        """
        super().__init__(personal_best)
        self.code = code
        self.secret_exit = False
        self.secret = False
        self.chapter_name = RecordHolder.get_chapter_name_by_code(code)
        self.final = False

        # set chapter_number, level_number, secret, secret_exit
        match self.code[0]:

            case "E": # doom1 E1M1 format
                self.chapter_number = int(self.code[1])
                self.level_number = int(self.code[3])
                if self.level_number == 9: # all secret levels in chapters 1-3 are number 9
                    # set the return back to normal levels to be one more than the secret_exit
                    self.secret = f"E{self.chapter_number}M{self._doom1_secret_exits[self.chapter_number-1]+1}"
                elif self.level_number == self._doom1_secret_exits[self.chapter_number-1]: #
                    self.secret_exit = f"E{self.chapter_number}M9" # again, all doom1 secret exits take you to level 9
                if self.level_number == 8:
                    self.final = True

            case "M": # doom 2 MAP01 format
                self.chapter_number = 5
                self.level_number = int(self.code[3:])
                # just set up doom 2's more complicated secret levels as a one-off
                # one is considered a super-secret level, so one secret level leads to another.
                match self.level_number:
                    case 15:
                        self.secret_exit = "MAP31"
                    case 31:
                        self.secret = "MAP16"
                        self.secret_exit = "MAP32"
                    case 32:
                        self.secret = "MAP16"
                    case 30:
                        self.final = True
            case _:
                raise Exception(f"Unknown level code: {self.code}")
        self.name = self._level_names[self.chapter_number-1][self.level_number-1]

    def __repr__(self):
            return f"Level({self.code}, modified={self.modified})"

    def start_timer(self, start_time: datetime) -> None:
        "Start recording a speedrun time for this level."
        self._race_start = start_time

    def stop_timer(self, stop_time: datetime) -> bool:
        """Stop recording a speedrun time for this level.
        Return True if a personal best was set, False if not.
        This method sets this object's self.personal_best, self.session_time, and self.diff"""
        try:
            self.session_time, self._backup_session_time = (stop_time - self._race_start), self.session_time
        except AttributeError:
            raise RuntimeError("stop_timer called before start_timer was called.")
        self._set_diff()
        del self._race_start
        return self._is_session_pb()

    def abort_timer(self) -> None:
        "Cancel the current timer without calculating anything. This should be done when the player dies or the game quits during a run."
        try:
            del self._race_start
        except AttributeError:
            raise RuntimeError("Level.abort_timer called when a timer wasn't started.")

    def get_current_time(self) -> str:
        """
        Return how much time has elapsed since the timer was started as a pretty time.
        Raise RuntimeError if a timer hasn't been started yet.
        """
        try:
            return self.pretty_time(datetime.now() - self._race_start)
        except AttributeError:
            raise RuntimeError("get_current_time called before start_timer was called.")

    def serialize(self) -> dict:
        "return a serialized version of this object for writing to disk. session_time and diff are omitted."
        try:
            return {"code": self.code,
                "pb_seconds": self.personal_best.seconds,
                "pb_microseconds": self.personal_best.microseconds}
        except AttributeError: # None.seconds
            raise SerializedEmpty("serialize called with no personal_best set.")


class Chapter(LevelChapter):
    "A single doom chapter. Contains Level objects."
    def __init__(self, chapter_number: int, levels: list=None, personal_best: timedelta=None):
        """
        chapter_number is the chapter number from the code, for example E1M1 -> 1.
        levels is a list of Level objects.
            If a level is missing from that list, a blank one will be created.
        session_time and personal_best refer to times for the entire chapter when run in order.

        name str: The name of the chapter like "Knee-Deep In The Dead".
        modified bool: Whether or not this chapter itself has been modified with a new personal_best that needs to be saved.
            This attribute does NOT mean that this chapter contains a modified level, use is_modified() for that.
        """
        super().__init__(personal_best)
        self.chapter_number = chapter_number
        self.name = RecordHolder.get_chapter_name_by_number(chapter_number)

        # set self.levels: a list of level objects for the entire chapter.
        if levels:
            self.levels = levels
            # Now create blank Level objects for the ones not provided by levels
            if self._is_doom1():
                for i in range(1, 10):
                    if self.levels[i-1].level_number != i:
                        self.levels.insert(i, Level(f"E{chapter_number}M{i}"))
            else: # doom2
                for i in range(1, 33):
                    if self.levels[i-1].level_number != i:
                        self.levels.insert(i, Level(f"MAP{str(i).zfill(2)}"))
        else: # levels was blank, fill self.levels with all blank objects
            if self._is_doom1():
                self.levels = [Level(f"E{chapter_number}M{level_number}") for level_number in range(1, 10)]
            else: # doom2
                self.levels = [Level(f"MAP{str(level_number).zfill(2)}") for level_number in range(1, 33)]

        self._valid_sequence = False # whether or not this chapter is being run in order from first level to last
        self._previous_level = None # used for the same task

    def __repr__(self):
        return f"Chapter({self.chapter_number}, modified={self.modified})"

    def start_timer(self, start_time: datetime, code: str) -> Level:
        "Start the timer for the contained level by code."
        self._current_level = self._get_level(code)
        self._current_level.start_timer(start_time)
        # figure out if the sequence is valid.
        if self._current_level.level_number == 1: # User started from the first level.
            self._valid_sequence = True
            self._previous_level = None
        elif self._valid_sequence: # User is on another level and the sequence has been good so far.
            # User went from one level to one out of order, figure out if it's because of a secret level.
            if self._current_level.level_number != getattr(self._previous_level, "level_number", 1)+1:
                # If the current level is NOT the secret from the previous or
                # if the previous level was NOT a secret and now we're back to the normal levels...
                if self._current_level.code not in (getattr(self._previous_level, "secret_exit", None),
                                                    getattr(self._previous_level, "secret", None)):
                    self._valid_sequence = False
                # else it was a proper secret path, _valid_sequence remains True
            # else the level_numbers have been sequential so we leave _valid_sequence set True
        return self._current_level

    def stop_timer(self, stop_time: datetime) -> dict:
        """
        Stop the timer for the currently active level.
        Return a dict with the following values:
            {"level": Level,
            "is_level_pb": bool,
            "is_chapter_session": bool,
            "is_chapter_pb": bool}
        """
        level = self._current_level
        del self._current_level
        is_level_pb = level.stop_timer(stop_time)
        if level.final and self._valid_sequence:
            self._backup_session_time = self.session_time
            self.session_time = timedelta(seconds=sum(session_time.total_seconds() for session_time in [x.session_time for x in self.levels if x.session_time]))
            is_chapter_session = True
            self._set_diff()
            is_chapter_pb = self._is_session_pb()
        else:
            is_chapter_pb = is_chapter_session = False
        self._previous_level = level
        return {"level": level, "is_level_pb": is_level_pb, "is_chapter_session": is_chapter_session, "is_chapter_pb": is_chapter_pb}

    def abort_timer(self) -> None:
        "Cancel the timer for the current level."
        try:
            self._current_level.abort_timer()
        except AttributeError:
            pass # it's already not present, nothing to abort
        else:
            del self._current_level
        self._previous_level = None
        self._valid_sequence = False

    def get_current_time(self) -> str:
        """
        Get the current elapsed time of the currently running level as a pretty_time.
        This must be run after start_timer and before stop_timer.
        No datetime arguments here as this for looks only and can be inaccurate.
        """
        try:
            return self._current_level.get_current_time()
        except AttributeError:
            raise RuntimeError(f"Chapter({self.chapter_number}).get_current_time: _current_level doesn't exist.")

    def is_modified(self) -> bool:
        "Return True if this chapter or any of it's levels have been modified."
        if self.modified:
            return True
        for level in self.levels:
            if level.modified:
                return True
        return False

    def serialize(self) -> dict:
        "Serialize this chapter and the contained levels. If the chapter or it's levels have no personal_best, None is returned."
        serialized_levels = [x.serialize() for x in self.levels if x.personal_best]
        if not self.personal_best and not serialized_levels:
            raise SerializedEmpty(f"Attempted to serialize empty Chapter({self.chapter_number})")
        return {"chapter_number": self.chapter_number,
                "pb_seconds": getattr(self.personal_best, "seconds", None),
                "pb_microseconds": getattr(self.personal_best, "microseconds", None),
                "levels": serialized_levels}

    def _get_level(self, code: str) -> Level:
        "return this chapter's level that corresponds with code."
        if self.chapter_number != RecordHolder.get_chapter_number_by_code(code):
            raise WrongChapter(f"{code=}, {self=}")
        if self._is_doom1():
            return self.levels[int(code.split("M")[1])-1]
        else: # doom2
            return self.levels[int(code.split("MAP")[1])-1]

    def _is_doom1(self) -> bool:
        "Return True if this is a doom1 chapter, False if it's doom2"
        return self.chapter_number < 5


class RecordHolder():
    """
    This object stores information about every category, difficulty, chapter, and level in the game.
    It also holds a database of all levels and their speedrun times.
    The class methods can be used directly rather than have an object created from it.
    When a "code" is referred to, this is a str like "E1M1" for Doom1, "MAP01" for Doom2.
    RecordHolder is a play on words, get it?
    """
    # Chapters match their indexes +1: CHAPTER[0] is E1, etc.
    # We consider Doom 2 the 5th chapter here, but beware that it uses a different level naming scheme
    categories = ("Any%", "100%", "Pacifist", "Noclip")
    difficulties = ("I'm Too Young To Die", "Hey, Not Too Rough", "Hurt Me Plenty", "Ultra-Violence", "Nightmare!")
    chapter_names = ("Knee-Deep In The Dead", "The Shores of Hell", "Inferno", "Thy Flesh Consumed", "Doom 2")

    def __init__(self, serialized: dict):
        "serialized is a dict of data from the FileDude, see it's documentation for more info."
        # create the nested dict structure of the database and fill it with blank Chapter and Level objects.
        self._db = dict.fromkeys(self.categories)
        for category in self.categories:
            self._db[category] = dict.fromkeys(self.difficulties)
            for difficulty in self.difficulties:
                self._db[category][difficulty] = []
                for chapter_number in range(1, 6):
                    if not serialized.get(category) or not serialized[category].get(difficulty): # if serialized has no category or difficulty...
                        # stuff serialized with an empty list so the next block of code works
                        serialized[category] = {k: [] for k in self.difficulties}
                    for chapter in serialized[category][difficulty]:
                        if chapter["chapter_number"] == chapter_number: # If the current chapter is in serialized...
                            try:
                                chapter_personal_best = timedelta(seconds=chapter["pb_seconds"], microseconds=chapter["pb_microseconds"])
                            except TypeError:
                                chapter_personal_best = None
                            levels = []
                            if chapter["chapter_number"] < 5: # if doom1
                                for i in range(1, 10):
                                    for level in chapter["levels"]:
                                        if i == int(level["code"][3]): # found the level
                                            levels.insert(i-1, Level(level["code"], personal_best=timedelta(seconds=level["pb_seconds"], microseconds=level["pb_microseconds"])))
                                            break
                                    else: # the level wasn't found in  serialized so add a blank one.
                                        levels.insert(i-1, Level(f"E{chapter_number}M{i}"))
                            else: # doom2
                                for i in range(1, 33):
                                    for level in chapter["levels"]:
                                        if i == int(level["code"][3:]): # found the level
                                            levels.insert(i-1, Level(level["code"], personal_best=timedelta(seconds=level["pb_seconds"], microseconds=level["pb_microseconds"])))
                                            break
                                    else: # the level wasn't found in  serialized so add a blank one.
                                        levels.insert(i-1, Level(level["code"]))
                            self._db[category][difficulty].insert(chapter_number-1, Chapter(chapter["chapter_number"], levels, personal_best=chapter_personal_best))
                            break
                    else: # chapter wasn't found in serialized, create a blank one
                        self._db[category][difficulty].insert(chapter_number-1, Chapter(chapter_number))

    def __repr__(self):
        return "RecordHolder()"

    def dump_database(self) -> dict:
        "Returns the entire database. Used for serializing to disk."
        return self._db

    def get_chapter(self, category: str, difficulty: str, chapter_name: str) -> Chapter:
        """
        Return the chapter object for a given category, difficulty, and name.
        If the chapter isn't found, raise KeyError.
        """
        return self._db[category][difficulty][self.get_chapter_number_by_name(chapter_name)-1]

    @classmethod
    def get_chapter_name_by_code(cls, code: str) -> str:
        "Get a chapter name from a code."
        try:
            return cls.chapter_names[int(code[1])-1] # doom1 style
        except ValueError: # int("A") so doom2 is being played
            return cls.chapter_names[4] # doom2 style

    @classmethod
    def get_chapter_name_by_number(cls, number: int) -> str:
        "get a chapter name from a chapter number. Doom2 is considered chapter 5."
        return cls.chapter_names[number-1]

    @classmethod
    def get_chapter_number_by_code(cls, code: str) -> int:
        "Get a chapter number from a code."
        try:
            return int(code[1]) # doom1
        except ValueError:
            return 5 # assume doom2

    @classmethod
    def get_chapter_number_by_name(cls, name: str) -> int:
        """
        Get the chapter number that name refers to.
        get_chapter_number_by_name("Inferno") -> 3
        If the chapter isn't found, raise KeyError.
        """
        try:
            return cls.chapter_names.index(name)+1
        except ValueError:
            raise KeyError(name)


class FileDude():
    """
    Saves and loads information from disk.
    The format of the dict of serialized data is a heirarchy of dicts:
    data[runs][category][difficulty][Chapter(1), ..., Chapter(5)]
    Note that only Levels and Chapters with personal_best times will be saved and loaded.
    """
    def __init__(self, save_file: str=None):
        "save_file is the path to the file to save and load. If unset, a default location is used."
        if save_file:
            self.config_file = save_file
        else:
            self.config_file = os.path.join(os.environ["HOME"], ".config", "gzdoom", "speedrun.json.bz2")

    def load(self) -> dict:
        """
        Load the data from disk and return it in a serialized format. Only the runs/records are returned.
        Call get_gui_config() after loading to get the gui config.
        If no file was found, return an empty dict.
        """
        try:
            d = json.loads(bz2.open(self.config_file, "rt").read())
        except FileNotFoundError: # No config file found, starting fresh.
            self._old_gui_config = {}
            return {}
        else:
            self._old_gui_config = d["gui_config"]
            return d["runs"]

    def save(self, runs: dict, gui_config: dict) -> None:
        """
        Serialize and save data to disk.
        runs is a dict of Chapters. If none of the runs were modified, runs should an empty dict or None.
        gui_config is a dict of configuration options from the MainWindow.
        """
        try:
            modified = gui_config != self._old_gui_config
        except AttributeError: # First run, no previous gui_config to compare
            modified = True

        serialized = {"gui_config": gui_config, # gui config is already a serialized dict
                      "runs": {}}

        for category in runs: # for each chapter in the passed in data...
            for difficulty in runs[category]:
                for chapter in runs[category][difficulty]:
                    try:
                        seralized_chapter = chapter.serialize()
                    except SerializedEmpty: # there's nothing to save, skip this whole chapter
                        continue
                    else:
                        if not modified:
                            modified = chapter.is_modified()
                        try: # try to add this chapter with an already existing dict structure
                            serialized["runs"][category][difficulty].append(seralized_chapter)
                        except KeyError: # back up one element at a time and try to create it, here we do the difficulty
                            try:
                                serialized["runs"][category] = {difficulty: [seralized_chapter]}
                            except KeyError: # create the category
                                serialized["runs"] = {category: {difficulty: [seralized_chapter]}}

        if modified: # don't actually write anything if nothing was modified
            bz2.open(self.config_file, 'wt').write(json.dumps(serialized))

    def get_gui_config(self) -> dict:
        "return the stored gui_config"
        return self._old_gui_config


class DoomRunner(Thread, QtCore.QObject):
    "Run gzdoom in a thread and indicate when levels begin and are completed."
    gzdoom_started = QtCore.pyqtSignal()
    gzdoom_quit = QtCore.pyqtSignal()
    level_started = QtCore.pyqtSignal(dict) # {"code": "E1M1", "name": "Hangar"}
    level_finished = QtCore.pyqtSignal()
    player_died = QtCore.pyqtSignal()
    def __init__(self):
        Thread.__init__(self)
        QtCore.QObject.__init__(self)

    def run(self) -> None:
        "Start gzdoom and call the callbacks when levels start and end. This should be run in a thread."
        # gzdoom output notes:
        # After a header (40 dashes) the following text is either the level name or a message about a secret followed by another header:
        #----------------------------------------
        #
        #MAP01 - Entryway
        # or
        #----------------------------------------
        #A secret is revealed!
        #----------------------------------------

        self.gzdoom_started.emit()
        proc = Popen(["stdbuf", "-oL", "gzdoom", "+developer", "3"] + argv[1:], stdout=PIPE)
        header_found = False
        skip_next_header = False
        while proc.poll() == None:
            line = proc.stdout.readline()
            if header_found:
                if line == b"\n": # This is the blank line between the header and level declaration
                    continue
                elif line == b"A secret is revealed!\n":
                    skip_next_header = True
                else:
                    try:
                        code, name = line.decode("utf-8").strip().split(" - ")
                    except ValueError: # not enough values to unpack, we didn't get the level info we expected.
                        continue # just keep trying
                    self.level_started.emit({"code": code, "name": name})
                header_found = False
            elif line == b'Starting all scripts of type 13 (Unloading)\n':
                self.level_finished.emit()
            elif line == b'Starting all scripts of type 3 (Death)\n':
                self.player_died.emit()
            elif line == b'----------------------------------------\n':
                if skip_next_header:
                    skip_next_header = False
                else:
                    header_found = True
        self.gzdoom_quit.emit()


class QChapter():
    "A Chapter that draws onto MainWindow. Methods with no documentation are just wrappers around Chapter, so check there for more info."
    _pb_color = QtGui.QColor.fromRgb(253, 224, 140) # the color of the background cell when a new personal best is set
    def __init__(self, chapter: Chapter, window: QtWidgets.QMainWindow):
        self.chapter = chapter
        self.window = window
        # Fill the QTableWidget immediately
        window.tableWidget.setRowCount(0)
        row = 0
        for level in chapter.levels:
            window.tableWidget.insertRow(row)
            window.tableWidget.setItem(row, 0, QtWidgets.QTableWidgetItem(level.name)) # don't use _make_centered_table_item here because we want level.name aligned left
            if level.session_time:
                window.tableWidget.setItem(row, 1, self._make_centered_table_item(level.pretty_time(level.session_time)))
            if level.personal_best:
                if getattr(level, "color_pb", False) and level.personal_best in level.color_pb:
                    self._insert_pb_table_item(row, level)
                else:
                    window.tableWidget.setItem(row, 2, self._make_centered_table_item(level.pretty_time(level.personal_best)))
                if level.session_time != level.personal_best:
                    window.tableWidget.setItem(row, 3, self._make_centered_table_item(level.diff))
            row += 1
        # Now add complete chapter to the bottom
        window.tableWidget.insertRow(row)
        window.tableWidget.setItem(row, 0, QtWidgets.QTableWidgetItem("Complete Chapter"))
        if chapter.session_time:
            window.tableWidget.setItem(row, 1, self._make_centered_table_item(level.pretty_time(chapter.session_time)))
        if chapter.personal_best:
            if getattr(chapter, "color_pb", False) and chapter.personal_best in chapter.color_pb:
                self._insert_pb_table_item(row, chapter)
            else:
                window.tableWidget.setItem(row, 2, self._make_centered_table_item(level.pretty_time(chapter.personal_best)))
            if chapter.session_time != chapter.personal_best:
                window.tableWidget.setItem(row, 3, self._make_centered_table_item(chapter.diff))

    def start_timer(self, start_time: datetime, code: str) -> None:
        level = self.chapter.start_timer(start_time, code)
        window.tableWidget.scrollToItem(window.tableWidget.item(0, level.level_number-1), QtWidgets.QAbstractItemView.PositionAtCenter)
        #window.tableWidget.selectRow(level.level_number-1) # highlighting the entire row means it doesn't show the PB background color until it's unselected
        window.tableWidget.setCurrentCell(level.level_number-1, 0)

    def stop_timer(self, stop_time: datetime) -> None:
        result = self.chapter.stop_timer(stop_time)
        level = result["level"]
        # set the lcd to match the final number in case the qtimer ending doesn't line up with us capturing the stop time.
        self.window.lcdNumber.display(level.pretty_time(level.session_time))
        self.window.statusbar.showMessage(f"{level.name} finished.")

        # Now show this new run info in the table:
        # Fill the session time
        self.window.tableWidget.setItem(level.level_number-1, 1, self._make_centered_table_item(level.pretty_time(level.session_time)))
        if result["is_level_pb"]: # fill the pb time if it was a pb
            self._insert_pb_table_item(level.level_number-1, level)
        self.window.tableWidget.setItem(level.level_number-1, 3, self._make_centered_table_item(level.diff)) # Fill the diff

        # Fill the complete chapter time if applicable
        if result["is_chapter_session"]:
            row = len(self.chapter.levels) # rows start at 0
            self.window.tableWidget.setItem(row, 1, self._make_centered_table_item(level.pretty_time(self.chapter.session_time)))
            if result["is_chapter_pb"]:
                self._insert_pb_table_item(row, self.chapter)
            self.window.tableWidget.setItem(row, 3, self._make_centered_table_item(self.chapter.diff))
            window.tableWidget.setCurrentCell(row, 0)

    def abort_timer(self) -> None:
        "End the timer without scoring it. This is used when the player dies or the game is closed during a run."
        try:
            window.timer.stop()
        except AttributeError: # timer hasn't been started
            pass
        self.chapter.abort_timer()

    def get_current_time(self) -> str:
        return self.chapter.get_current_time()

    def revert_cell(self, column: int, row: int) -> None:
        "Revert cell to previously held data, like an undo. column must be 1 or 2 because level and diff cannot be reverted."
        self._revert_or_delete_cell(column, row, revert=True)

    def delete_cell(self, column: int, row: int) -> None:
        self._revert_or_delete_cell(column, row, delete=True)

    def _revert_or_delete_cell(self, column: int, row: int, revert=False, delete=False) -> None:
        "Helper method to revert or delete a cell. Only one of revert, delete MUST be True."
        try:
            levelchapter = self.chapter.levels[row]
        except IndexError: # User tried to revert the full chapter time
            levelchapter = self.chapter
        if column == 1:
            if delete:
                levelchapter.delete_session_time()
            else:
                levelchapter.revert_session_time()
            # draw the new session time to the time column
            if levelchapter.session_time:
                self.window.tableWidget.setItem(row, 1, self._make_centered_table_item(levelchapter.pretty_time(levelchapter.session_time)))
            else:
                self.window.tableWidget.takeItem(row, 1)
        elif column == 2:
            if delete:
                levelchapter.delete_personal_best()
            else:
                levelchapter.revert_personal_best()
            if levelchapter.personal_best:
                if getattr(levelchapter, "color_pb", False) and levelchapter.personal_best in levelchapter.color_pb:
                    self._insert_pb_table_item(row, levelchapter)
                else: # insert pb time with no color
                    self.window.tableWidget.setItem(row, 2, self._make_centered_table_item(levelchapter.pretty_time(levelchapter.personal_best)))
            else:
                self.window.tableWidget.takeItem(row, 2)
        else:
            raise Exception(f"Invalid column passed to Qchapter.revert_cell: {(column, row)}")
        # update the diff no matter which was just changed
        if (levelchapter.session_time and levelchapter.personal_best) and levelchapter.session_time != levelchapter.personal_best:
            self.window.tableWidget.setItem(row, 3, self._make_centered_table_item(levelchapter.diff))
        else:
            self.window.tableWidget.takeItem(row, 3) # make it blank if session_time or PB are blank or if they're the same.

    def _make_centered_table_item(self, text: str) -> QtWidgets.QTableWidgetItem:
        "helper method to create a centered item for the TableWidget."
        item = QtWidgets.QTableWidgetItem(text)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        return item

    def _insert_pb_table_item(self, row: int, level: Level or Chapter) -> None:
        "helper method to create a centered and gold background item and insert it into the TableWidget."
        # Set a list of PB times to indicate if a PB was set this session.
        # This way if you get a PB and then beat it, it'll always show up gold.
        # This ensures that the cell will be colored even if you change chapters or revert back and forth
        try:
            if level.personal_best not in level.color_pb:
                level.color_pb.append(level.personal_best)
        except AttributeError: # level.color_pb doesn't exist
            level.color_pb = [level.personal_best]
        else:
            level.color_pb = level.color_pb[-2:] # limit this list to 2 items like a deque
        item = self._make_centered_table_item(level.pretty_time(level.personal_best))
        item.setBackground(self._pb_color)
        self.window.tableWidget.setItem(row, 2, item)


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        # Initialize default gui
        self.setupUi(self)
        #self.tableWidget.setHorizontalHeaderLabels(["Level", "Time", "PB", "Diff"]) # changed to specifying these in mainwindow.ui
        self.tableWidget.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.comboBox_category.addItems(RecordHolder.categories)
        self.comboBox_category.setFocus()
        self.comboBox_difficulty.addItems(RecordHolder.difficulties)
        self.comboBox_chapter.addItems(RecordHolder.chapter_names)
        self.action_revert = QtWidgets.QAction(self.style().standardIcon(QtWidgets.QStyle.SP_DialogResetButton), "&Revert", self)
        self.action_delete = QtWidgets.QAction(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon), "&Delete", self)
        for attr in self.action_revert, self.action_delete:
            self.tableWidget.addAction(attr)
        self.toolButton_help.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogHelpButton))

        # set up the main logic
        self.file_dude = FileDude()
        serialized_db = self.file_dude.load()
        if not serialized_db:
            self.statusbar.showMessage("No database found, starting fresh.")
        else:
            self.statusbar.showMessage("Ready.")
        self.record_holder = RecordHolder(serialized_db)

        # set gui to be as it was when last run
        if gui_config := self.file_dude.get_gui_config():
            self.comboBox_category.setCurrentText(gui_config["category"])
            self.comboBox_difficulty.setCurrentText(gui_config["difficulty"])
            self.comboBox_chapter.setCurrentText(gui_config["chapter_name"])
            self.resize(*gui_config["window_size"])
            self.comboBox_changed() # load the table

        # connect signals and slots
        self.comboBox_category.currentIndexChanged.connect(self.comboBox_changed)
        self.comboBox_difficulty.currentIndexChanged.connect(self.comboBox_changed)
        self.comboBox_chapter.currentIndexChanged.connect(self.comboBox_changed)
        self.pushButton_gzdoom.pressed.connect(self.start_gzdoom_pressed)
        self.action_revert.triggered.connect(self.revert_clicked)
        self.action_delete.triggered.connect(self.delete_clicked)
        self.tableWidget.itemSelectionChanged.connect(self.table_selection_changed)
        self.toolButton_help.clicked.connect(self.help_clicked)

        self.start_gzdoom_pressed()

    @QtCore.pyqtSlot(dict)
    def level_started(self, level_info: dict) -> None:
        "This is called when a new level is started in gzdoom."
        # First take a snapshot of the time before we do any further processing
        self.timer_start_time = datetime.now()
        while True:
            try: # start the level's timer
                self.qchapter.start_timer(self.timer_start_time, level_info["code"])
            except WrongChapter: # The chapter combobox doesn't match the level, so change the combobox to match. Loop and try again.
                self._set_chapter_combobox_by_code(level_info["code"])
            except AttributeError: # self.qchapter not set because a level was started without a category or difficulty set
                if not hasattr(self, "qchapter"):
                    missing = [] # find out what we're missing.
                    if not self.comboBox_category.currentText():
                        missing.append("category")
                    if not self.comboBox_difficulty.currentText():
                        if missing:
                            missing.append("and")
                        missing.append("difficulty")
                    if not missing: # if category and difficulty are set, just change the chapter to what it should be
                        self._set_chapter_combobox_by_code(level_info["code"])
                        continue
                    elif len(missing) == 1:
                        missing.append("is")
                    else:
                        missing.append("are")
                    self.statusbar.showMessage(f"Not recording time because {' '.join(missing)} not set.")
                    return
                else:
                    raise
            else:
                break
        # Set up the lcdNumber timer
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.lcd_timer_expired)
        self.timer.start(10)

        self.statusbar.showMessage(f"New level started: {level_info['code']} {level_info['name']}")
        self._comboboxes_enabled(False) # don't allow changes while a run is in progress.

    @QtCore.pyqtSlot()
    def level_finished(self) -> None:
        "This is called when a level ends in gzdoom."
        stop_time = datetime.now()
        if hasattr(self, "qchapter"):
            self.timer.stop()
            self.qchapter.stop_timer(stop_time)
        else:
            self.statusbar.showMessage("Level finished with no recording because category or difficulty is not set.")
        self._comboboxes_enabled(True)

    @QtCore.pyqtSlot()
    def start_gzdoom_pressed(self) -> None:
        "The start gzdoom button was pressed."
        self.doom_runner = DoomRunner()
        self.doom_runner.level_started.connect(self.level_started)
        self.doom_runner.level_finished.connect(self.level_finished)
        self.doom_runner.gzdoom_started.connect(self.gzdoom_started)
        self.doom_runner.gzdoom_quit.connect(self.gzdoom_quit)
        self.doom_runner.player_died.connect(self.player_died)
        self.doom_runner.start()

    @QtCore.pyqtSlot()
    def gzdoom_started(self) -> None:
        "This is called gzdoom is launched."
        self.pushButton_gzdoom.setEnabled(False)
        self.pushButton_gzdoom.setToolTip("Gzdoom is running.")
        self.statusbar.showMessage("gzdoom started.")

    @QtCore.pyqtSlot()
    def gzdoom_quit(self) -> None:
        "This is called when gzdoom is exited."
        self.pushButton_gzdoom.setEnabled(True)
        status_msg = "gzdoom exited."
        self.pushButton_gzdoom.setToolTip("Gzdoom is running.")
        if not self.comboBox_category.isEnabled(): # poor man's check if timer is running
            self._abort_timer(status_msg)
        else:
            self.statusbar.showMessage(status_msg)

    @QtCore.pyqtSlot()
    def player_died(self) -> None:
        "The player died, so discard the current run progress."
        self._abort_timer("Player died, run aborted.")

    @QtCore.pyqtSlot()
    def lcd_timer_expired(self) -> None:
        "The very short timer has expired, so update the lcdNumber."
        try:
            self.lcdNumber.display(self.qchapter.get_current_time())
        except RuntimeError: # tried to get the current time after a level has ended
            return

    def get_gui_config(self) -> dict:
        "return the current state of the gui so it can be saved to disk on exit."
        return {"category": self.comboBox_category.currentText(),
                "difficulty": self.comboBox_difficulty.currentText(),
                "chapter_name": self.comboBox_chapter.currentText(),
                "window_size": (self.frameGeometry().width(), self.frameGeometry().height())}

    @QtCore.pyqtSlot()
    def comboBox_changed(self) -> None:
        "One of the comboBoxes has been changed, reload the table."
        try:
            self.qchapter = QChapter(self.record_holder.get_chapter(self.comboBox_category.currentText(), self.comboBox_difficulty.currentText(), self.comboBox_chapter.currentText()), self)
        except KeyError: # One combobox was changed while the others were blank
            return

    @QtCore.pyqtSlot()
    def revert_clicked(self) -> None:
        "The revert context menu was clicked in a cell."
        for cell in self._get_selected_cells():
            self.qchapter.revert_cell(*cell)

    @QtCore.pyqtSlot()
    def delete_clicked(self) -> None:
        "The delete context menu was clicked in a cell."
        for cell in self._get_selected_cells():
            self.qchapter.delete_cell(*cell)

    @QtCore.pyqtSlot()
    def table_selection_changed(self) -> None:
        if self._get_selected_cells() is None:
            self.action_revert.setDisabled(True)
            self.action_delete.setDisabled(True)
        else:
            self.action_revert.setDisabled(False)
            self.action_delete.setDisabled(False)

    @QtCore.pyqtSlot()
    def help_clicked(self) -> None:
        "The help button was clicked."
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Information)
        #msg.setInformativeText("Help")
        msg.setWindowTitle("Help")
        msg.setText(
            f"""How to use GZdoom Speedrun Timer

Select a category and difficulty from the dropdown menus. The chapter will be set automatically by the game.

If you pause or bring up the menu, your speedrun time will not be paused. Times recorded by this program do not match the in-game time. Your times are recorded to the millionth of a second, but rounded to hundredths of a second when displayed.

Loading a saved game is timed as if it's the start of the level.

If you play all the levels in order with optional secret levels, you will be given a complete chapter time. This complete chapter time does not include time spent on the score screen between levels.

If you mess up a speedrun, right click on the time and revert or delete it. Deleting a level will not effect it's complete chapter time, so delete that too if necessary.

The configuration file for this program is saved to:
{self.file_dude.config_file}.

Arguments given to this program will be passed onto gzdoom, but don't change the developer output options.
""")
        msg.exec_()


    def _abort_timer(self, status_msg: str) -> None:
        "helper method to abort a run in progress and show a statusbar message."
        self.timer.stop()
        self.qchapter.abort_timer()
        self._comboboxes_enabled(True)
        self.statusbar.showMessage(status_msg)

    def _set_chapter_combobox_by_code(self, code: str) -> None:
        "Change the Chapter combobox to reflect code."
        self.comboBox_chapter.setCurrentText(RecordHolder.get_chapter_name_by_code(code))

    def _comboboxes_enabled(self, state: bool) -> None:
        "Set the category, difficulty, and chapter combobox enabled state."
        for attr in self.comboBox_category, self.comboBox_difficulty, self.comboBox_chapter:
            attr.setEnabled(state)

    def _get_selected_cells(self) -> list or None:
        """
        Helper method to return a list of every currently selected cell: [(1, 1), ...]
        Return None if an invalid cell is selected.
        The first and last columns are invalid; you can't revert or delete the level name or diff.
        """
        result = []
        for selected_range in self.tableWidget.selectedRanges():
            for column in range(selected_range.leftColumn(), selected_range.rightColumn()+1):
                for row in range(selected_range.topRow(), selected_range.bottomRow()+1):
                    if 0 < column < 3:
                        result.append((column, row))
                    else:
                        return None
        return result


if __name__ == '__main__':
    app = QtWidgets.QApplication([False])
    app.setApplicationName("Doom Speedrun Timer")
    window = MainWindow()
    window.show()
    app.exec()
    window.file_dude.save(window.record_holder.dump_database(), window.get_gui_config())
