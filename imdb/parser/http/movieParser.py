"""
parser.http.movieParser module (imdb package).

This module provides the classes (and the instances), used to parse the
IMDb pages on the akas.imdb.com server about a movie.
E.g., for Brian De Palma's "The Untouchables", the referred
pages would be:
    combined details:   http://akas.imdb.com/title/tt0094226/combined
    plot summary:       http://akas.imdb.com/title/tt0094226/plotsummary
    ...and so on...

Copyright 2004-2006 Davide Alberani <da@erlug.linux.it>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""

from urllib import unquote

from imdb.Person import Person
from imdb.Movie import Movie
from imdb.utils import analyze_title, re_episodes
from imdb._exceptions import IMDbParserError
from utils import ParserBase


_stypes = (type(u''), type(''))


def strip_amps(theString):
    """Remove '&\s*' at the end of a string.
    It's used to remove '& ' from strings like '(written by) & '.
    """
    i = theString.rfind('&')
    if i != -1:
        if not theString[i+1:] or theString[i+1:].isspace():
            # There's nothing except spaces after the '&'.
            theString = theString[:i].rstrip()
    return theString


def clear_text(theString):
    """Remove separators and spaces in excess."""
    # Squeeze multiple spaces into one.
    theString = ' '.join(theString.split())
    # Remove spaces around the '::' separator.
    theString = theString.replace(':: ', '::').replace(' ::', '::')
    # Remove exceeding '::' separators.  I love list comprehension! <g>
    theString = '::'.join([piece for piece in theString.split('::') if piece])
    return theString


class HTMLMovieParser(ParserBase):
    """Parser for the "combined details" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        mparser = HTMLMovieParser()
        result = mparser.parse(combined_details_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _init(self):
        self.__movie_data = {}
        # If true, we're parsing the "maindetails" page; if false,
        # the "combined" page is expected.
        self.mdparse = 0

    def _reset(self):
        self.__movie_data.clear()
        # XXX: this is quite a mess; the boolean variables below are
        #      used to identify what section of the HTML we're parsing,
        #      and the string variables are used to store temporary values.
        # The name of the section we're parsing.
        self.__current_section = ''
        # We're in a cast/crew section.
        self.__is_cast_crew = 0
        # We're managing the name of a person.
        self.__is_name = 0
        # The name and his role, (temporary) sperated by '::'.
        self.__name = u''
        self.__cur_nameID = ''
        # We're in a company credit section.
        self.__is_company_cred = 0
        # The name of the company.
        self.__company_data = ''
        self.__countries = 0
        self.__is_genres = 0
        self.__is_title = 0
        self.__title = u''
        self.__title_short = u'' # used to retrieve the cover URL.
        self.__is_rating = 0
        self.__rating = ''
        self.__is_languages = 0
        self.__is_akas = 0
        self.__aka_title = u''
        self.__is_movie_status = 0
        self.__movie_status_sect = ''
        self.__movie_status = ''
        self.__is_runtimes = 0
        self.__runtimes = ''
        self.__is_mpaa = 0
        self.__mpaa = ''
        self.__inbch = 0
        self.__isplotoutline = 0
        self.__plotoutline = u''
        # If true, the next data should be merged with the previous one,
        # without the '::' separator.
        self.__merge_next = 0
        # Counter for the billing position in credits.
        self._counter = 1

    def append_item(self, sect, data):
        """Append a new value in the given section of the dictionary."""
        # Do some cleaning work on the strings.
        sect = clear_text(sect)
        data = clear_text(data)
        self.__movie_data.setdefault(sect, []).append(data)

    def set_item(self, sect, data):
        """Put a single value (a string, normally) in the dictionary."""
        if type(data) in _stypes:
            data = clear_text(data)
        self.__movie_data[clear_text(sect)] = data

    def get_data(self):
        """Return the dictionary."""
        return self.__movie_data

    def start_title(self, attrs):
        self.__is_title = 1

    def end_title(self):
        if self.__title:
            self.__is_title = 0
            d_title = analyze_title(self.__title)
            for key, item in d_title.items():
                self.set_item(key, item)
            self.__title_short = d_title.get('title', u'').lower()

    def start_table(self, attrs): pass

    def end_table(self):
        self.__is_cast_crew = 0
        self.__is_company_cred = 0
        self.__current_section = ''
        self.__is_movie_status = 0
        self.__is_runtimes = 0
        self.__runtimes = ''

    def start_a(self, attrs):
        # XXX: the current section ('director', 'cast', 'production company',
        #      etc.) name is taken from two different sources: for sections
        #      that contains actors/crew member names, the section name in
        #      the HTML is in the form
        #      <a href="/Glossary/S#SectName/">Description</a>, so we use
        #      the lowecase "sectname" as the name of the current section.
        #      For sections with company credits, the HTML is in the form
        #      <a href="/List?SectName=...">CompanyName</a> so we cut the
        #      href attribute of the <a> tag to get the "sectname".
        #      Underscores and minus signs in section names are replaced
        #      with spaces.
        link = self.get_attr_value(attrs, 'href')
        if not link: return
        olink = link
        link = link.lower()
        if link.startswith('/name'):
            # The following data will be someone's name.
            self.__is_name = 1
            ids = self.re_imdbID.findall(link)
            if ids:
                self.__cur_nameID = ids[-1]
        elif link.startswith('/list'):
            self.__is_company_cred = 1
            # Sections like 'company credits' all begin
            # with a link to "/List" page.
            sect = link[6:].replace('_', ' ').replace('-', ' ')
            # The section name ends at the first '='.
            ind = sect.find('=')
            if ind != -1:
                sect = sect[:ind]
            self.__current_section = sect
        # Sections like 'cast', 'director', 'writer', etc. all
        # begin with a link to a "/Glossary" page.
        elif link.startswith('/glossary'):
            self.__is_cast_crew = 1
            # Get the section name from the link.
            link = link[12:].replace('_', ' ').replace('-', ' ')
            self.__current_section = link
        elif link.startswith('/sections/countries'):
            self.__countries = 1
        elif link.startswith('/sections/genres'):
            self.__is_genres = 1
        elif link.startswith('/sections/languages'):
            self.__is_languages = 1
        elif link.startswith('/mpaa'):
            self.__is_mpaa = 1
        elif self.__isplotoutline:
            self.__isplotoutline = 0
            if self.__plotoutline:
                self.set_item('plot outline', self.__plotoutline)
        elif link.startswith('http://pro.imdb.com'):
            self.__is_movie_status = 0
        elif link.startswith('/titlebrowse?') and \
                    not self.__movie_data.has_key('title'):
            try:
                d_title = analyze_title(unquote(olink[13:]))
                for key, item in d_title.items():
                    self.set_item(key, item)
                self.__title_short = d_title.get('title', u'').lower()
            except IMDbParserError:
                pass

    def end_a(self): pass

    def start_tr(self, attrs): pass

    def end_tr(self):
        if self.__is_name and self.__current_section:
            # Every cast/crew information are separated by <tr> tags.
            if self.__is_cast_crew:
                # Strip final '&' (and spaces); this is here
                # to get rid of things like the "& " in "(novel) & ".
                self.__name = strip_amps(self.__name)
                n_split = self.__name.split('::')
                n = n_split[0].strip()
                del n_split[0]
                role = ' '.join(n_split).strip()
                notes = u''
                ii = role.find('(')
                if ii != -1:
                    ei = role.rfind(')')
                    if ei != -1:
                        notes = role[ii:ei+1].strip()
                        role = '%s%s' % (role[:ii], role[ei+1:])
                        role = role.replace('  ', ' ').strip()
                sect = clear_text(self.__current_section)
                if sect != 'cast':
                    if notes: notes = ' %s' % notes
                    notes = role + notes
                    role = u''
                if sect == 'crewmembers': sect = 'miscellaneous crew'
                # Create a Person object.
                # XXX: check for self.__cur_nameID?
                #      maybe it's not a good idea; is it possible for
                #      a person to be listed without a link?
                p = Person(name=n, currentRole=role,
                        personID=str(self.__cur_nameID), accessSystem='http')
                if notes: p.notes = notes
                if self.__movie_data.setdefault(sect, []) == []:
                    self._counter = 1
                p.billingPos = self._counter
                self.__movie_data[sect].append(p)
                self._counter += 1
            self.__name = u''
            self.__cur_nameID = ''
        self.__movie_status_data = ''
        self.__movie_status_sect = ''
        self.__is_name = 0

    def start_td(self, attrs): pass

    def end_td(self):
        if self.__is_movie_status:
            if self.__movie_status_sect and self.__movie_status_data:
                sect_name = self.__movie_status_sect
                if not sect_name.startswith('status'):
                    sect_name = 'status %s' % sect_name
                self.set_item(sect_name, self.__movie_status_data)
        elif self.__is_cast_crew and self.__current_section:
            if self.__is_name:
                self.__name += '::'
    
    def do_br(self, attrs):
        if self.__is_company_cred:
            # Sometimes companies are separated by <br> tags.
            self.__company_data = strip_amps(self.__company_data)
            self.append_item(self.__current_section, self.__company_data)
            self.__company_data = ''
            self.__is_company_cred = 0
        elif self.__is_akas and self.__aka_title:
            # XXX: when managing an 'aka title', some transformation
            #      are required; a complete aka title is in the form
            #      of "Aka Title (year) (country1) (country2) [cc]"
            #      The movie's year of release; the "Aka Title", the
            #      countries list and the country code (cc) will be
            #      separated by '::'.
            #      In the example: "Aka Title::(country1) (country2)::[cc]"
            aka = self.__aka_title
            year = None
            title = self.__movie_data.get('title')
            if title:
                year = self.__movie_data.get('year')
            if year:
                syear = ' (%s) ' % year
                if aka.find(syear) != -1:
                    aka = aka.replace(syear, '(%s)::' % year)
                else:
                    fsti = aka.find(' (')
                    if fsti != -1:
                        aka = aka[:fsti] + '::' + aka[fsti+1:]
                    aka = aka.replace(')', ')::')
            ind = aka.rfind(' [')
            if ind != -1:
                aka = aka[:ind] + '::' + aka[ind+1:]
            aka = aka.replace('][', '] [')
            aka = aka.replace(')(', ') (')
            self.append_item('akas', aka)
            self.__aka_title = ''
        elif self.__is_mpaa and self.__mpaa:
            self.__is_mpaa = 0
            mpaa = self.__mpaa.replace('MPAA:', '')
            self.set_item('mpaa', mpaa)
        elif self.__isplotoutline:
            self.__isplotoutline = 0
            if self.__plotoutline:
                self.set_item('plot outline', self.__plotoutline)
        elif self.__is_runtimes and self.__runtimes:
            self.__is_runtimes = 0
            rt = self.__runtimes.replace(' min', '')
            # The "(xy episodes)" note.
            episodes = re_episodes.findall(rt)
            if episodes:
                rt = re_episodes.sub('', rt)
                self.set_item('episodes', episodes[0])
            rl = [x.strip() for x in rt.split('/')]
            if rl: self.set_item('runtimes', rl)
        if self.mdparse:
            self.end_tr()

    def start_li(self, attrs): pass

    def end_li(self):
        if self.__is_company_cred:
            # Sometimes companies are listed inside an <ul> tag.
            self.__company_data = strip_amps(self.__company_data)
            self.append_item(self.__current_section, self.__company_data)
            self.__company_data = ''
            self.__is_company_cred = 0

    def start_ul(self, attrs): pass

    def end_ul(self):
        self.__is_company_cred = 0

    def start_b(self, attrs):
        self.__is_akas = 0
        cls = self.get_attr_value(attrs, 'class')
        if cls:
            cls = cls.lower()
            if cls == 'ch':
                self.__inbch = 1
            elif self.mdparse and cls == 'blackcatheader':
                self.end_table()

    def end_b(self):
        if self.__inbch: self.__inbch = 0

    def do_img(self, attrs):
        alttex = self.get_attr_value(attrs, 'alt')
        if not alttex: return
        alttex = alttex.strip().lower()
        if alttex in ('*', '_'):
            # The gold and grey stars; we're near the rating and number
            # of votes.
            self.__is_rating = 1
        # XXX: I've a report about alttex==self.__movie_data.get('title')
        #      in some situations, but I'm not sure.
        elif alttex == 'cover' or alttex == self.__title_short:
            # Get the URL of the cover image.
            src = self.get_attr_value(attrs, 'src')
            if src: self.set_item('cover url', src)
        elif alttex == 'vote here':
            # Parse the rating and the number of votes.
            self.__is_rating = 0
            rav = self.__rating.strip()
            if rav:
                i = rav.find('/10')
                if i != -1:
                    rating = rav[:i]
                    try:
                        rating = float(rating)
                        self.set_item('rating', rating)
                    except ValueError:
                        pass
                i = rav.find('(')
                if i != -1:
                    votes = rav[i+1:]
                    j = votes.find(' ')
                    votes = votes[:j].replace(',', '')
                    try:
                        votes = int(votes)
                        self.set_item('votes', votes)
                    except ValueError:
                        pass

    def _handle_data(self, data):
        # Manage the plain text part of an HTML document.
        sdata = data.strip()
        sldata = sdata.lower()
        if self.__is_cast_crew and self.__current_section and self.__is_name:
            # Modify the separator for "name .... role"
            data = data.replace(' .... ', '::')
            # Separate the last (...) string; it's here to handle strings
            # like 'screenplay' in "name (screenplay)" in the writing credits.
            if sdata and sdata[0] == '(':
                data = data.lstrip()
                self.__name = self.__name.strip() + '::'
            self.__name += data
        elif self.__is_company_cred and self.__current_section:
            # Sometimes company credits are separated by a slash;
            # 'certification' is an example.
            if sdata == '/':
                cd = self.__company_data
                cd = strip_amps(cd)
                self.append_item(self.__current_section, cd)
                self.__company_data = ''
                self.__is_company_cred = 0
            else:
                # Merge the next data without a separator.
                if self.__merge_next:
                    self.__company_data += data
                    self.__merge_next = 0
                else:
                    if self.__company_data:
                        if len(data) > 1:
                            self.__company_data += '::'
                        elif data != ' ':
                            self.__merge_next = 1
                    self.__company_data += data
        elif self.__is_akas and sdata != ':':
            self.__aka_title += data
        elif self.__is_runtimes:
            self.__runtimes += data
        elif self.__is_mpaa:
            self.__mpaa += data
        elif self.__is_movie_status:
            if not self.__movie_status_sect:
                self.__movie_status_sect = sldata.replace(':', '')
            else:
                self.__movie_status_data += data.lower()
        elif self.__countries:
            self.append_item('countries', data)
            self.__countries = 0
        elif self.__is_title:
            # Store the title and the year, as taken from the <title> tag.
            self.__title += data
        elif self.__is_genres:
            self.append_item('genres', data)
            self.__is_genres = 0
        elif self.__is_rating:
            self.__rating += data
        elif self.__is_languages:
            self.append_item('languages', data)
            self.__is_languages = 0
        elif self.__isplotoutline:
            self.__plotoutline += data
        elif self.__inbch and sldata.startswith('plot outline:'):
            self.__isplotoutline = 1
        elif sldata.startswith('also known as'):
            self.__is_akas = 1
        elif sldata.startswith('runtime:'):
            self.__is_runtimes = 1
        elif sldata.startswith('production notes/status'):
            self.__is_movie_status = 1
        # XXX: the following branches are here to manage the "maindetails"
        #      page of a movie, instead of the "combined" page.
        if self.mdparse:
            if sldata.startswith('cast overview, first billed only'):
                self.__is_cast_crew = 1
                self.__current_section = 'cast'
            elif sldata.startswith('directed by'):
                self.__is_cast_crew = 1
                self.__current_section = 'director'
            elif sldata.startswith('writing credits'):
                self.__is_cast_crew = 1
                self.__current_section = 'writer'


class HTMLPlotParser(ParserBase):
    """Parser for the "plot summary" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a 'plot' key, containing a list
    of string with the structure: 'summary_author <author@email>::summary'.
    
    Example:
        pparser = HTMLPlotParser()
        result = pparser.parse(plot_summary_html_string)
    """
    def _init(self):
        self.__plot_data = {}

    def _reset(self):
        """Reset the parser."""
        self.__plot_data.clear()
        self.__is_plot = 0
        self.__plot = u''
        self.__last_plot = u''
        self.__is_plot_writer = 0
        self.__plot_writer = u''

    def get_data(self):
        """Return the dictionary with the 'plot' key."""
        return self.__plot_data

    def start_p(self, attrs):
        pclass = self.get_attr_value(attrs, 'class')
        if pclass and pclass.lower() == 'plotpar':
            self.__is_plot = 1

    def end_p(self):
        if self.__is_plot:
            # Store the plot in the self.__last_plot variable until
            # the parser will read the name of the author.
            self.__last_plot = self.__plot
            self.__is_plot = 0
            self.__plot = u''

    def start_a(self, attrs):
        link = self.get_attr_value(attrs, 'href')
        # The next data is the name of the author.
        if link and link.lower().startswith('/searchplotwriters'):
            self.__is_plot_writer = 1

    def end_a(self):
        # We've read the name of an author and the summary he wrote;
        # store everything in __plot_data.
        if self.__is_plot_writer and self.__last_plot:
            writer = self.__plot_writer.strip()
            # Replace funny email separators.
            writer = writer.replace('{', '<').replace('}', '>')
            plot = self.__last_plot.strip()
            self.__plot_data.setdefault('plot', []).append('%s::%s' %
                                                            (writer, plot))
            self.__is_plot_writer = 0
            self.__plot_writer = u''
            self.__last_plot = u''
            
    def _handle_data(self, data):
        # Store text for plots and authors.
        if self.__is_plot:
            self.__plot += data
        if self.__is_plot_writer:
            self.__plot_writer += data


class HTMLAwardsParser(ParserBase):
    """Parser for the "awards" page of a given person or movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        awparser = HTMLAwardsParser()
        result = awparser.parse(awards_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _init(self):
        self.__aw_data = []
        # We're managing awards for a person or a movie?
        self.subject = 'title'
    
    def _reset(self):
        """Reset the parser."""
        self.__aw_data = []
        self.__is_big = 0
        self.__is_current_assigner = 0
        self.__begin_aw = 0
        self.__in_td = 0
        self.__cur_year = ''
        self.__cur_result = ''
        self.__cur_notes = ''
        self.__cur_category = ''
        self.__cur_forto = u''
        self.__cur_assigner = u''
        self.__cur_award = u''
        self.__cur_sect = ''
        self.__no = 0
        self.__rowspan = 0
        self.__counter = 1
        self.__limit = 1
        self.__is_tn = 0
        self.__cur_id = ''
        self.__t_o_n = u''
        self.__to = []
        self.__for = []
        self.__with = []
        self.__begin_to_for = 0
        self.__cur_role = u''
        self.__cur_tn = u''
        # XXX: a Person or Movie object is instantiated only once (i.e.:
        #      every reference to a given movie/person is the _same_
        #      object).
        self.__person_obj_list = []
        self.__movie_obj_list = []

    def get_data(self):
        """Return the dictionary."""
        if not self.__aw_data: return {}
        return {'awards': self.__aw_data}

    def start_big(self, attrs):
        self.__is_big = 1

    def end_big(self):
        self.__is_big = 0

    def start_td(self, attrs):
        self.__in_td = 1
        if not self.__begin_aw: return
        rowspan = self.get_attr_value(attrs, 'rowspan') or '1'
        try: rowspan = int(rowspan)
        except (ValueError, OverflowError):
            rowspan = 1
        self.__rowspan = rowspan
        colspan = self.get_attr_value(attrs, 'colspan') or '1'
        try: colspan = int(colspan)
        except (ValueError, OverflowError):
            colspan = 1
        if colspan == 4:
            self.__no = 1

    def end_td(self):
        if self.__no or not self.__begin_aw: return
        if self.__cur_sect == 'year':
            self.__cur_sect = 'res'
        elif self.__cur_sect == 'res':
            self.__limit = self.__rowspan
            self.__counter = 1
            self.__cur_sect = 'award'
        elif self.__cur_sect == 'award':
            self.__cur_sect = 'cat'
        elif self.__cur_sect == 'cat':
           self.__counter += 1
           self.store_data()
           self.__begin_to_for = 0
           # XXX: if present, the next "Category/Recipient(s)"
           #      has a different "Result", so go back and read it.
           if self.__counter == self.__limit+1:
                self.__cur_result = ''
                self.__cur_award = u''
                self.__cur_sect = 'res'
                self.__counter = 1

    def store_data(self):
        year = self.__cur_year.strip()
        res = self.__cur_result.strip()
        aw = self.__cur_award.strip()
        notes = self.__cur_notes.strip()
        assign = self.__cur_assigner.strip()
        cat = self.__cur_category.strip()
        d = {'year': year, 'result': res, 'award': aw, 'notes': notes,
            'assigner': assign, 'category': cat, 'for': self.__for,
            'to': self.__to, 'with': self.__with}
        # Remove empty keys.
        for key in d.keys():
            if not d[key]: del d[key]
        self.__aw_data.append(d)
        self.__cur_notes = u''
        self.__cur_category = ''
        self.__cur_forto = u''
        self.__with = []
        self.__to = []
        self.__for = []
        self.__cur_role = u''
        
    def start_th(self, attrs):
        self.__begin_aw = 0

    def end_th(self): pass

    def start_table(self, attrs): pass

    def end_table(self):
        self.__begin_aw = 0
        self.__in_td = 0

    def start_small(self, attrs):
        self.__is_small = 1

    def end_small(self):
        self.__is_small = 0

    def start_a(self, attrs):
        href = self.get_attr_value(attrs, 'href')
        if not href: return
        if href.startswith('/Sections/Awards'):
            if self.__in_td:
                try: year = str(int(href[-4:]))
                except (ValueError, TypeError): year = None
                if year:
                    self.__cur_sect = 'year'
                    self.__cur_year = year
                    self.__begin_aw = 1
                    self.__counter = 1
                    self.__limit = 1
                    self.__no = 0
                    self.__cur_result = ''
                    self.__cur_notes = u''
                    self.__cur_category = ''
                    self.__cur_forto = u''
                    self.__cur_award = ''
                    self.__with = []
                    self.__to = []
                    self.__for = []
            if self.__is_big:
                self.__is_current_assigner = 1
                self.__cur_assigner = ''
        elif href.startswith('/name') or href.startswith('/title'):
            if self.__is_small: return
            tn = self.re_imdbID.findall(href)
            if tn:
                self.__cur_id = tn[-1]
                self.__is_tn = 1
                self.__cur_tn = u''
                if href.startswith('/name'): self.__t_o_n = 'n'
                else: self.__t_o_n = 't'

    def end_a(self):
        if self.__is_current_assigner:
            self.__is_current_assigner = 0
        if self.__is_tn and self.__cur_sect == 'cat':
            self.__cur_tn = self.__cur_tn.strip()
            self.__cur_role = self.__cur_role.strip()
            if self.subject == 'name':
                if self.__t_o_n == 't':
                    self.__begin_to_for = 1
                    m = Movie(title=self.__cur_tn,
                                movieID=str(self.__cur_id),
                                accessSystem='http')
                    if m in self.__movie_obj_list:
                        ind = self.__movie_obj_list.index(m)
                        m = self.__movie_obj_list[ind]
                    else:
                        self.__movie_obj_list.append(m)
                    self.__for.append(m)
                else:
                    p = Person(name=self.__cur_tn,
                                personID=str(self.__cur_id),
                                currentRole=self.__cur_role,
                                accessSystem='http')
                    if p in self.__person_obj_list:
                        ind = self.__person_obj_list.index(p)
                        p = self.__person_obj_list[ind]
                    else:
                        self.__person_obj_list.append(p)
                    self.__with.append(p)
            else:
                if self.__t_o_n == 't':
                    m = Movie(title=self.__cur_tn,
                                movieID=str(self.__cur_id),
                                accessSystem='http')
                    if m in self.__movie_obj_list:
                        ind = self.__movie_obj_list.index(m)
                        m = self.__movie_obj_list[ind]
                    else:
                        self.__movie_obj_list.append(m)
                    self.__with.append(m)
                else:
                    self.__begin_to_for = 1
                    p = Person(name=self.__cur_tn,
                                personID=str(self.__cur_id),
                                currentRole=self.__cur_role,
                                accessSystem='http')
                    if p in self.__person_obj_list:
                        ind = self.__person_obj_list.index(p)
                        p = self.__person_obj_list[ind]
                    else:
                        self.__person_obj_list.append(p)
                    self.__to.append(p)
            self.__cur_role = u''
        self.__is_tn = 0

    def _handle_data(self, data):
        if self.__is_current_assigner:
            self.__cur_assigner += data
        if not self.__begin_aw or not data or data.isspace() or self.__no:
            return
        sdata = data.strip()
        sldata = sdata.lower()
        if self.__cur_sect == 'res':
            self.__cur_result += data
        elif self.__cur_sect == 'award':
            self.__cur_award += data
        elif self.__cur_sect == 'cat':
            if self.__is_tn:
                self.__cur_tn += data
            elif sldata not in ('for:', 'shared with:'):
                if self.__is_small:
                    self.__cur_notes += data
                elif self.__begin_to_for:
                    self.__cur_role += data
                else:
                    self.__cur_category += data


class HTMLTaglinesParser(ParserBase):
    """Parser for the "taglines" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        tparser = HTMLTaglinesParser()
        result = tparser.parse(taglines_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__in_tl = 0
        self.__in_tlu = 0
        self.__in_tlu2 = 0
        self.__tl = []
        self.__ctl = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__tl: return {}
        return {'taglines': self.__tl}

    def start_td(self, attrs):
        # XXX: not good!
        self.__in_tlu = 1

    def end_td(self):
        self.__in_tl = 0
        self.__in_tlu = 0
        self.__in_tlu2 = 0

    def start_h1(self, attrs): pass

    def end_h1(self):
        if self.__in_tlu2:
            self.__in_tl = 1

    def start_p(self, attrs): pass
    
    def end_p(self):
        if self.__in_tl and self.__ctl:
            self.__tl.append(self.__ctl.strip())
            self.__ctl = ''

    def _handle_data(self, data):
        if self.__in_tl:
            self.__ctl += data
        elif self.__in_tlu and data.lower().find('taglines for') != -1:
            self.__in_tlu2 = 1


class HTMLKeywordsParser(ParserBase):
    """Parser for the "keywords" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        kwparser = HTMLKeywordsParser()
        result = kwparser.parse(keywords_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__in_kw = 0
        self.__kw = []
        self.__ckw = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__kw: return {}
        return {'keywords': self.__kw}

    def start_b(self, attrs):
        if self.get_attr_value(attrs, 'class') == 'keyword':
            self.__in_kw = 1

    def end_b(self):
        if self.__in_kw:
            self.__kw.append(self.__ckw.strip())
            self.__ckw = ''
            self.__in_kw = 0

    def start_a(self, attrs):
        if not self.__in_kw: return
        href = self.get_attr_value(attrs, 'href')
        if not href: return
        kwi = href.find('keyword/')
        if kwi == -1: return
        kw = href[kwi+8:].strip()
        if not kw: return
        if kw[-1] == '/': kw = kw[:-1].strip()
        if kw: self.__ckw = kw

    def end_a(self): pass


class HTMLAlternateVersionsParser(ParserBase):
    """Parser for the "alternate versions" and "trivia" pages of a
    given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        avparser = HTMLAlternateVersionsParser()
        result = avparser.parse(alternateversions_html_string)
    """
    def _init(self):
        self.kind = 'alternate versions'

    def _reset(self):
        """Reset the parser."""
        self.__in_av = 0
        self.__in_avd = 0
        self.__av = []
        self.__cav = ''
        self.__stlist = []
        self.__curst = {}
        self.__cur_title = ''
        self.__curinfo = ''

    def get_data(self):
        """Return the dictionary."""
        if self.kind == 'soundtrack':
            if self.__stlist:
                return {self.kind: self.__stlist}
            else:
                return {}
        if not self.__av: return {}
        return {self.kind: self.__av}

    def start_ul(self, attrs):
        if self.get_attr_value(attrs, 'class') == 'trivia':
            self.__in_av = 1

    def end_ul(self):
        self.__in_av = 0
        
    def start_li(self, attrs):
        if self.__in_av:
            self.__in_avd = 1

    def end_li(self):
        if self.__in_av and self.__in_avd:
            if self.kind == 'soundtrack':
                self.__stlist.append(self.__curst.copy())
                self.__curst.clear()
                self.__cur_title = ''
                self.__curinfo = ''
            else:
                self.__av.append(self.__cav.strip())
            self.__in_avd = 0
            self.__cav = ''

    def do_br(self, attrs):
        if self.__in_avd and self.kind == 'soundtrack':
            if not self.__cur_title:
                self.__cav = self.__cav.strip()
                if self.__cav and self.__cav[-1] == '"':
                    self.__cav = self.__cav[:-1]
                if self.__cav and self.__cav[0] == '"':
                    self.__cav = self.__cav[1:]
                self.__cur_title = self.__cav
                self.__curst[self.__cur_title] = {}
                self.__cav = ''
            else:
                lcw = self.__cav.lower()
                for i in ('with', 'by', 'from', 'of'):
                    posi = lcw.find(i)
                    if posi != -1:
                        self.__curinfo = self.__cav[:posi+len(i)]
                        if self.kind == 'soundtrack':
                            self.__curinfo = self.__curinfo.lower().strip()
                        rest = self.__cav[posi+len(i)+1:]
                        self.__curst[self.__cur_title][self.__curinfo] = \
                                rest
                        break
                else:
                    if not lcw.strip(): return
                    if not self.__curst[self.__cur_title].has_key('misc'):
                        self.__curst[self.__cur_title]['misc'] = ''
                    if self.__curst[self.__cur_title]['misc'] and \
                            self.__curst[self.__cur_title]['misc'][-1] != ' ':
                        self.__curst[self.__cur_title]['misc'] += ' '
                    self.__curst[self.__cur_title]['misc'] += self.__cav
                self.__cav = ''

    def _handle_data(self, data):
        if self.__in_avd:
            self.__cav += data


class HTMLCrazyCreditsParser(ParserBase):
    """Parser for the "crazy credits" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        ccparser = HTMLCrazyCreditsParser()
        result = ccparser.parse(crazycredits_html_string)
    """

    def _reset(self):
        """Reset the parser."""
        self.__in_cc = 0
        self.__in_cc2 = 0
        self.__cc = []
        self.__ccc = ''
        self.__nrbr = 0

    def get_data(self):
        """Return the dictionary."""
        if not self.__cc: return {}
        return {'crazy credits': self.__cc}

    def start_td(self, attrs):
        # XXX: not good!
        self.__in_cc = 1

    def end_td(self):
        self.__in_cc = 0

    def start_pre(self, attrs):
        if self.__in_cc:
            self.__in_cc2 = 1
    
    def end_pre(self):
        if self.__in_cc2:
            self.app()
            self.__in_cc2 = 0

    def do_br(self, attrs):
        if not self.__in_cc2: return
        self.__nrbr += 1
        if self.__nrbr == 2:
            self.app()

    def app(self):
        self.__ccc = self.__ccc.strip()
        if self.__in_cc2 and self.__ccc:
            self.__cc.append(self.__ccc.replace('\n', ' '))
            self.__ccc = ''
            self.__nrbr = 0
    
    def _handle_data(self, data):
        if self.__in_cc2:
            self.__ccc += data


class HTMLGoofsParser(ParserBase):
    """Parser for the "goofs" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        gparser = HTMLGoofsParser()
        result = gparser.parse(goofs_html_string)
    """
    def _reset(self):
        """Reset the parser."""
        self.__in_go = 0
        self.__in_go2 = 0
        self.__go = []
        self.__cgo = ''
        self.__in_gok = 0
        self.__cgok = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__go: return {}
        return {'goofs': self.__go}

    def start_ul(self, attrs):
        if self.get_attr_value(attrs, 'class') == 'trivia':
            self.__in_go = 1

    def end_ul(self):
        self.__in_go = 0
        
    def start_b(self, attrs):
        if self.__in_go2:
            self.__in_gok = 1

    def end_b(self):
        self.__in_gok = 0
            
    def start_li(self, attrs):
        if self.__in_go:
            self.__in_go2 = 1

    def end_li(self):
        if self.__in_go and self.__in_go2:
            self.__in_go2 = 0
            self.__go.append('%s:%s' % (self.__cgok.strip().lower(),
                                        self.__cgo.strip()))
            self.__cgo = ''
            self.__cgok = ''

    def _handle_data(self, data):
        if self.__in_gok:
            self.__cgok += data
        elif self.__in_go2:
            self.__cgo += data


class HTMLQuotesParser(ParserBase):
    """Parser for the "memorable quotes" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        qparser = HTMLQuotesParser()
        result = qparser.parse(quotes_html_string)
    """
    def _reset(self):
        """Reset the parser."""
        self.__in_quo = 0
        self.__in_quo2 = 0
        self.__quo = []
        self.__cquo = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__quo: return {}
        quo = []
        for q in self.__quo:
            if q.endswith('::'): q = q[:-2]
            quo.append(q)
        return {'quotes': quo}

    def start_td(self, attrs):
        # XXX: not good!
        self.__in_quo = 1

    def end_td(self):
        self.__in_quo = 0
        self.__in_quo2 = 0

    def start_a(self, attrs):
        name = self.get_attr_value(attrs, 'name')
        if name and name.startswith('qt'):
            self.__in_quo2 = 1
    
    def end_a(self): pass

    def do_hr(self, attrs):
        if self.__in_quo and self.__in_quo2 and self.__cquo:
            self.__cquo = self.__cquo.strip()
            if self.__cquo.endswith('::'):
                self.__cquo = self.__cquo[:-2]
            self.__quo.append(self.__cquo.strip())
            self.__cquo = ''

    def do_p(self, attrs):
        if self.__in_quo and self.__in_quo2:
            self.do_hr([])
            self.__in_quo = 0

    def do_br(self, attrs):
        if self.__in_quo and self.__in_quo2 and self.__cquo:
            self.__cquo = '%s::' % self.__cquo.strip()
    
    def _handle_data(self, data):
        if self.__in_quo and self.__in_quo2:
            data = data.replace('\n', ' ')
            if self.__cquo.endswith('::'):
                data = data.lstrip()
            self.__cquo += data


class HTMLReleaseinfoParser(ParserBase):
    """Parser for the "release dates" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        rdparser = HTMLReleaseinfoParser()
        result = rdparser.parse(releaseinfo_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__in_rl = 0
        self.__in_rl2 = 0
        self.__rl = []
        self.__crl = ''
        self.__is_country = 0

    def get_data(self):
        """Return the dictionary."""
        if not self.__rl: return {}
        return {'release dates': self.__rl}

    def start_th(self, attrs):
        if self.get_attr_value(attrs, 'class') == 'xxxx':
            self.__in_rl = 1

    def end_th(self): pass
        
    def start_a(self, attrs):
        if self.__in_rl:
            href = self.get_attr_value(attrs, 'href')
            if href and href.startswith('/Recent'):
                self.__in_rl2 = 1
                self.__is_country = 1

    def end_a(self):
        if self.__is_country:
            if self.__crl:
                self.__crl += '::'
            self.__is_country = 0
     
    def start_tr(self, attrs): pass

    def end_tr(self):
        if self.__in_rl2:
            self.__in_rl2 = 0
            self.__rl.append(self.__crl)
            self.__crl = ''

    def _handle_data(self, data):
        if self.__in_rl2:
            if self.__crl and self.__crl[-1] not in (' ', ':') \
                    and not data.isspace():
                self.__crl += ' '
            self.__crl += data.strip()


class HTMLRatingsParser(ParserBase):
    """Parser for the "user ratings" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        rparser = HTMLRatingsParser()
        result = rparser.parse(userratings_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__in_t = 0
        self.__in_total = 0
        self.__in_b = 0
        self.__cur_nr = ''
        self.__in_cur_vote = 0
        self.__cur_vote = ''
        self.__first = 0
        self.__votes = {}
        self.__rank = {}
        self.__demo = {}
        self.__in_p = 0
        self.__in_demo = 0
        self.__in_demo_t = 0
        self.__cur_demo_t = ''
        self.__cur_demo_av = ''
        self.__next_is_demo_vote = 0
        self.__next_demo_vote = ''
        self.__in_td = 0

    def get_data(self):
        """Return the dictionary."""
        data = {}
        if self.__votes:
            data['number of votes'] = self.__votes
        if self.__demo:
            data['demographic'] = self.__demo
        data.update(self.__rank)
        return data

    def start_table(self, attrs):
        self.__in_t = 1

    def end_table(self):
        self.__in_t = 0
        self.__in_total = 0

    def start_b(self, attrs):
        self.__in_b = 1

    def end_b(self):
        self.__in_b = 0

    def start_td(self, attrs):
        self.__in_td = 1

    def end_td(self):
        self.__in_td = 0
        if self.__in_total:
            if self.__first:
                self.__first = 0

    def start_tr(self, attrs):
        if self.__in_total:
            self.__first = 1

    def end_tr(self):
        if self.__in_total:
            if self.__cur_nr:
                try:
                    c = int(self.__cur_vote)
                    n = int(self.__cur_nr)
                    self.__votes[c] = n
                except (ValueError, OverflowError): pass
                self.__cur_nr = ''
                self.__cur_vote = ''
        if self.__in_demo:
            self.__in_demo = 0
            try:
                av = float(self.__cur_demo_av)
                dv = int(self.__next_demo_vote)
                self.__demo[self.__cur_demo_t] = (dv, av)
            except (ValueError, OverflowError): pass
            self.__cur_demo_av = ''
            self.__next_demo_vote = ''
            self.__cur_demo_t = ''

    def start_p(self, attrs):
        self.__in_p = 1

    def end_p(self):
        self.__in_p = 0
    
    def start_a(self, attrs):
        href = self.get_attr_value(attrs, 'href')
        if href and href.startswith('ratings-'):
            self.__in_demo = 1
            self.__in_demo_t = 1

    def end_a(self):
        self.__in_demo_t = 0
    
    def _handle_data(self, data):
        if self.__in_b and data == 'Rating':
            self.__in_total = 1
        sdata = data.strip()
        if not sdata: return
        if self.__first:
            self.__cur_nr = sdata
        else:
            self.__cur_vote = sdata
        if self.__in_p:
            if sdata.startswith('Ranked #'):
                sd = sdata[8:]
                i = sd.find(' ')
                if i != -1:
                    sd = sd[:i]
                    try: sd = int(sd)
                    except (ValueError, OverflowError): pass
                    if type(sd) is type(1):
                        self.__rank['top 250 rank'] = sd
            elif sdata.startswith('Arithmetic mean = '):
                if sdata[-1] == '.': sdata = sdata[:-1]
                am = sdata[18:]
                try: am = float(am)
                except (ValueError, OverflowError): pass
                if type(am) is type(1.0):
                    self.__rank['arithmetic mean'] = am
            elif sdata.startswith('Median = '):
                med = sdata[9:]
                try: med = int(med)
                except (ValueError, OverflowError): pass
                if type(med) is type(1):
                    self.__rank['median'] = med
        if self.__in_demo:
            if self.__next_is_demo_vote:
                self.__next_demo_vote = sdata
                self.__next_is_demo_vote = 0
            elif self.__in_demo_t:
                self.__cur_demo_t = sdata.lower()
                self.__next_is_demo_vote = 1
            else:
                self.__cur_demo_av = sdata
        elif self.__in_td and sdata.startswith('All votes'):
            self.__in_demo = 1
            self.__next_is_demo_vote = 1
            self.__cur_demo_t = 'all votes'


class HTMLOfficialsitesParser(ParserBase):
    """Parser for the "official sites", "external reviews", "newsgroup
    reviews", "miscellaneous links", "sound clips", "video clips" and
    "photographs" pages of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        osparser = HTMLOfficialsitesParser()
        result = osparser.parse(officialsites_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _init(self):
        self.kind = 'official sites'
    
    def _reset(self):
        """Reset the parser."""
        self.__in_os = 0
        self.__in_os2 = 0
        self.__in_os3 = 0
        self.__os = []
        self.__cos = ''
        self.__cosl = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__os: return {}
        return {self.kind: self.__os}

    def start_td(self, attrs):
        # XXX: not good at all!
        self.__in_os = 1

    def end_td(self):
        self.__in_os = 0

    def start_ol(self, attrs):
        if self.__in_os:
            self.__in_os2 = 1
    
    def end_ol(self):
        if self.__in_os2:
            self.__in_os2 = 0

    def start_li(self, attrs):
        if self.__in_os2:
            self.__in_os3 = 1

    def end_li(self):
        if self.__in_os3:
            self.__in_os3 = 0
            if self.__cosl and self.__cos:
                self.__os.append((self.__cos.strip(), self.__cosl.strip()))
            self.__cosl = ''
            self.__cos = ''

    def start_a(self, attrs):
        if self.__in_os3:
            href = self.get_attr_value(attrs, 'href')
            if href:
                if not href.lower().startswith('http://'):
                    if href.startswith('/'): href = href[1:]
                    href = 'http://akas.imdb.com/%s' % href
                self.__cosl = href
        
    def end_a(self): pass
    
    def _handle_data(self, data):
        if self.__in_os3:
            self.__cos += data


class HTMLConnectionParser(ParserBase):
    """Parser for the "connections" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        connparser = HTMLConnectionParser()
        result = connparser.parse(connections_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__in_cn = 0
        self.__in_cnt = 0
        self.__cn = {}
        self.__cnt = ''
        self.__cur_id = ''
        self.__mtitle = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__cn: return {}
        return {'connections': self.__cn}

    def start_dt(self, attrs):
        self.__in_cnt = 1
        self.__cnt = ''

    def end_dt(self):
        self.__in_cnt = 0

    def start_dd(self, attrs):
        self.__in_cn = 1

    def end_dd(self):
        self.__in_cn = 0
        self.__cur_id = ''

    def start_a(self, attrs):
        href = self.get_attr_value(attrs, 'href')
        if not (self.__in_cn and href and href.startswith('/title')): return
        tn = self.re_imdbID.findall(href)
        if tn:
            self.__cur_id = tn[-1]
    
    def end_a(self): pass

    def do_br(self, attrs):
        sectit = self.__cnt.strip()
        if self.__in_cn and self.__mtitle and self.__cur_id and sectit:
            m = Movie(title=self.__mtitle,
                        movieID=str(self.__cur_id),
                        accessSystem='http')
            self.__cn.setdefault(sectit, []).append(m)
            self.__mtitle = ''
            self.__cur_id = ''

    def _handle_data(self, data):
        if self.__in_cn:
            self.__mtitle += data
        elif self.__in_cnt:
            self.__cnt += data.lower()


class HTMLTechParser(ParserBase):
    """Parser for the "technical", "business", "literature",
    "publicity" (for people) and "locations" pages of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        tparser = HTMLTechParser()
        result = tparser.parse(technical_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _init(self):
        self.kind = 'something else'
    
    def _reset(self):
        """Reset the parser."""
        self.__tc = {}
        self.__dotc = 0
        self.__indt = 0
        self.__indd = 0
        self.__cur_sect = ''
        self.__curdata = ['']
    
    def get_data(self):
        """Return the dictionary."""
        if self.kind == 'locations':
            rl = []
            for item in self.__tc.items():
                tmps = item[0].strip() + ' ' + \
                        ' '.join([x.strip() for x in item[1]])
                rl.append(tmps)
            if rl: return {'locations': rl}
        if self.kind in ('literature', 'business') and self.__tc:
            return {self.kind: self.__tc}
        return self.__tc

    def start_dl(self, attrs):
        self.__dotc = 1

    def end_dl(self):
        self.__dotc = 0

    def start_dt(self, attrs):
        if self.__dotc: self.__indt = 1

    def end_dt(self):
        self.__indt = 0

    def start_tr(self, attrs): pass

    def end_tr(self):
        if self.__indd and self.kind == 'publicity':
            if self.__curdata:
                self.do_br([])

    def start_td(self, attrs): pass

    def end_td(self):
        if self.__indd and self.__curdata and self.kind == 'publicity':
            if self.__curdata[-1].find('::') == -1:
                self.__curdata[-1] += '::'

    def start_p(self, attrs): pass

    def end_p(self):
        if self.__indd and self.kind == 'publicity':
            if self.__curdata:
                self.__curdata[-1] += '::'
                self.do_br([])

    def start_dd(self, attrs):
        if self.__dotc: self.__indd = 1

    def end_dd(self):
        self.__indd = 0
        self.__curdata[:] = [x.strip() for x in self.__curdata]
        self.__curdata[:] = [x for x in self.__curdata if x]
        for i in xrange(len(self.__curdata)):
            if self.__curdata[i][-2:] == '::':
                self.__curdata[i] = self.__curdata[i][:-2]
        if self.__cur_sect and self.__curdata:
            self.__tc[self.__cur_sect] = self.__curdata[:]
        self.__curdata[:] = ['']
        self.__cur_sect = ''

    def do_br(self, attrs):
        if self.__indd:
            self.__curdata += ['']

    def _handle_data(self, data):
        if self.__indd:
            self.__curdata[-1] += data
        elif self.__indt:
            if self.kind != 'locations': data = data.lower()
            self.__cur_sect += data


class HTMLDvdParser(ParserBase):
    """Parser for the "dvd" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        dparser = HTMLDvdParser()
        result = dparser.parse(dvd_html_string)
    """
    # TODO: it's not still ready to handle the "laserdisc" page.
    kind = 'dvd'

    def _init(self):
        self.__dvd = []

    def _reset(self):
        """Reset the parser."""
        self.__cdvd = {}
        self.__indvd = 0
        self.__intitle = 0
        self.__curtitle = ''
        self.__binfo = 0
        self.__binfo_txt = ''
        self.__inth = 0
        self.__noendb = 0
        self.__finfo = 0
        self.__finfo_txt = ''
        self.__inar = 0
        self.__thl = []
        self.__thmult = 1
        self.__colcount = -1
        self.__coldata = ''
        self.__insound = 0

    def get_data(self):
        """Return the dictionary."""
        if self.__dvd: return {'dvd': self.__dvd}
        return {}

    def _put_data(self, s):
        s = s.strip()
        if not s: return
        dcmi = s.find('::-')
        mini = s.find('min')
        if dcmi != -1 and mini != -1:
            self._put_data('color::%s' % s[:dcmi])
            self._put_data('runtime::%s' % s[dcmi+3:mini])
            return
        ss = [x.strip() for x in s.split('::') if x.strip()]
        ssl = len(ss)
        if ssl == 1:
            if ss[0].lower().find('read about how we rate dvds') != -1: return
            self.__cdvd.setdefault('misc', []).append(ss[0])
        else:
            k = ss[0].lower()
            v = ' '.join(ss[1:]).replace('\n', '')
            if self.__cdvd.has_key(k) and type(self.__cdvd[k]) is not type([]):
                self.__cdvd[k] = [self.__cdvd[k]]
            if self.__cdvd.has_key(k):
                self.__cdvd[k] += v
            else:
                self.__cdvd[k] = v

    def do_hr(self, attrs):
        if self.__indvd and self.__cdvd:
            self.__dvd.append(self.__cdvd.copy())
            self._reset()

    def start_a(self, attrs):
        name = self.get_attr_value(attrs, 'name')
        if name and len(name) > 1 and name[0] == "X":
            self.__indvd = 1
        if not self.__indvd: return
        href = self.get_attr_value(attrs, 'href')
        hrefl = href
        if href: hrefl = href.lower()
        if hrefl and hrefl.find('sections/dvds/labels') != -1:
            self.__binfo_txt = 'label::'
            self.__noendb = 1
        elif hrefl and hrefl.find('sections/dvds/pictureformats') != -1:
            self.__binfo_txt = 'picture format::'
            self.__noendb = 1
        elif hrefl and hrefl.find('sections/dvds/regions') != -1:
            self.__finfo_txt = 'region::'
        elif hrefl and hrefl.find('sections/dvds/video') != -1:
            self.__finfo_txt = 'video standard::'
        elif hrefl and hrefl.find('sections/dvds/packaging') != -1:
            self.__finfo_txt = 'packaging::'

    def end_a(self): pass

    def do_br(self, attrs):
        if self.__indvd:
            if self.__intitle: self.__curtitle += ' - '
            if self.__binfo:
                self.__binfo = 0
                if self.__binfo_txt:
                    self._put_data(self.__binfo_txt)
                    self.__binfo_txt = ''

    def start_table(self, attrs):
        self.__thl = []

    def end_table(self):
        if self.__insound: self.__insound = 0

    def start_th(self, attrs):
        if self.__indvd:
            self.__inth = 1
            span = self.get_attr_value(attrs, 'colspan')
            if span:
                try:self.__thmult = int(span)
                except (ValueError, OverflowError): pass

    def end_th(self):
        self.__inth = 0

    def start_tr(self, attrs):
        if not self.__indvd: return
        if self.__thl:
            self.__colcount = -1

    def end_tr(self): pass

    def start_td(self, attrs):
        if not self.__indvd: return
        if self.__thl:
            self.__colcount += 1
            self.__colcount %= len(self.__thl)

    def end_td(self):
        if not self.__indvd: return
        if self.__thl:
            self.__coldata = self.__coldata.strip()
            if not self.__coldata: return
            if not self.__insound:
                k = self.__thl[self.__colcount]
                v = self.__coldata.strip().replace('\n', ' ').replace('  ', ' ')
                if v.find('::') != -1:
                    v = [x.strip() for x in v.split('::') if x.strip()]
                if not (k and v): return
                self.__cdvd[k] = v
            else:
                if not self.__cdvd.has_key('sound'): self.__cdvd['sound'] = {}
                lang = self.__thl[self.__colcount].lower()
                self.__cdvd['sound'][lang] = self.__coldata
            self.__coldata = ''

    def start_li(self, attrs):
        if self.__indvd and self.__thl and self.__coldata.strip():
            self.__coldata += '::'

    def end_li(self): pass
            
    def start_h3(self, attrs):
        if self.__indvd:
            self.__intitle = 1

    def end_h3(self):
        if self.__indvd:
            self.__intitle = 0
            self.__cdvd['title'] = self.__curtitle

    def start_font(self, attrs):
        if not self.__indvd: return
        cls = self.get_attr_value(attrs, 'class')
        if cls and cls.lower() in ('catheader', 'smalltxt') and \
                not self.__inth and not self.__binfo:
            self.__finfo = 1

    def end_font(self):
        if not self.__indvd: return
        if self.__finfo:
            self.__finfo = 0
            self.__finfo_txt = self.__finfo_txt.strip()
            if self.__finfo_txt:
                self._put_data(self.__finfo_txt)
                self.__finfo_txt = ''

    def do_img(self, attrs):
        src = self.get_attr_value(attrs, 'src')
        if src and src.lower().find('images.amazon.com') != -1:
            self.__cdvd['cover'] = src

    def start_b(self, attrs):
        if self.kind == 'laserdisc':
            cls = self.get_attr_value(attrs, 'class')
            if cls and cls.lower() == 'ch':
                if not self.__indvd:
                    self.__indvd = 1
        if not self.__indvd: return
        cls = self.get_attr_value(attrs, 'class')
        if cls and cls.lower() in ('catheader', 'smalltxt', 'aspectratio') \
                and not self.__inth:
            self.__binfo = 1
            self.__binfo_txt = ''
            if cls.lower() == 'aspectratio': self.__inar = 1

    def end_b(self):
        if self.__binfo:
            self.__binfo_txt = self.__binfo_txt.strip()
            if self.__binfo_txt:
                if self.__binfo_txt[-1] == ':':
                    self.__binfo_txt = self.__binfo_txt[:-1]
                sep = '::'
                if self.__noendb:
                    sep = ' '
                    self.__noendb = 0
                self.__binfo_txt += sep
            if  self.__inar:
                self.__inar = 0
                self.__binfo_txt = self.__binfo_txt.replace(' : ', ':')
                self._put_data('aspect ratio::%s' % self.__binfo_txt)

    def _handle_data(self, data):
        if self.__indvd:
            if self.__inth:
                dsl = data.replace(':', '').strip().lower()
                self.__thl += [dsl]*self.__thmult
                if dsl == 'sound':
                    self.__insound = 1
            if self.__intitle:
                self.__curtitle += data
            elif self.__binfo:
                sdata = data.lstrip()
                if sdata:
                    self.__binfo_txt += sdata
            elif self.__finfo:
                sdata = data.lstrip()
                if sdata:
                    self.__finfo_txt += sdata
            elif self.__thl and not self.__inth:
                self.__coldata += data


class HTMLRecParser(ParserBase):
    """Parser for the "recommendations" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        rparser = HTMLRecParser()
        result = rparser.parse(recommendations_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__rec = {}
        self.__firsttd = 0
        self.__curlist = ''
        self.__curtitle = ''
        self.__startgath = 0
        self.__intable = 0
        self.__inb = 0
        self.__cur_id = ''
    
    def get_data(self):
        if not self.__rec: return {}
        return {'recommendations': self.__rec}

    def start_a(self, attrs):
        if self.__firsttd:
            href = self.get_attr_value(attrs, 'href')
            if href:
                tn = self.re_imdbID.findall(href)
                if tn:
                    self.__cur_id = tn[-1]

    def end_a(self): pass

    def start_table(self, attrs):
        self.__intable = 1

    def end_table(self):
        self.__intable = 0
        self.__startgath = 0

    def start_tr(self, attrs):
        self.__firsttd = 1

    def end_tr(self): pass

    def start_td(self, attrs):
        if self.__firsttd:
            span = self.get_attr_value(attrs, 'colspan')
            if span: self.__firsttd = 0

    def end_td(self):
        if self.__firsttd:
            self.__curtitle = clear_text(self.__curtitle)
            if self.__curtitle:
                if self.__curlist:
                    if self.__cur_id:
                        m = Movie(movieID=str(self.__cur_id),
                                    title=self.__curtitle,
                                    accessSystem='http')
                        self.__rec.setdefault(self.__curlist, []).append(m)
                        self.__cur_id = ''
                self.__curtitle = ''
            self.__firsttd = 0

    def start_b(self, attrs):
        self.__inb = 1

    def end_b(self):
        self.__inb = 0

    def _handle_data(self, data):
        ldata = data.lower()
        if self.__intable and self.__inb:
            if ldata.find('suggested by the database') != -1:
                self.__startgath = 1
                self.__curlist = 'database'
            elif ldata.find('imdb users recommend') != -1:
                self.__startgath = 1
                self.__curlist = 'users'
        elif self.__firsttd and self.__curlist:
            self.__curtitle += data


class HTMLNewsParser(ParserBase):
    """Parser for the "news" page of a given movie or person.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        nwparser = HTMLNewsParser()
        result = nwparser.parse(news_html_string)
    """

    def _reset(self):
        """Reset the parser."""
        self.__intable = 0
        self.__inh1 = 0
        self.__innews = 0
        self.__cur_news = {}
        self.__news = []
        self.__cur_stage = 'title'
        self.__cur_text = ''
        self.__cur_link = ''

    def get_data(self):
        """Return the dictionary."""
        if not self.__news: return {}
        return {'news': self.__news}

    def start_table(self, attrs):
        self.__intable = 1

    def end_table(self):
        self.__intable = 0
        self.__innews = 0

    def start_h1(self, attrs):
        self.__inh1 = 1

    def end_h1(self):
        self.__inh1 = 0

    def start_p(self, attrs): pass

    def end_p(self):
        if self.__innews:
            if self.__cur_news:
                self.__news.append(self.__cur_news)
                self.__cur_news = {}
            self.__cur_stage = 'title'
            self.__cur_text = ''

    def do_br(self, attrs):
        if self.__innews:
            self.__cur_text = self.__cur_text.strip()
            if self.__cur_text:
                if self.__cur_stage == 'body':
                    if self.__cur_news.has_key('body'):
                        bodykey = self.__cur_news['body']
                        if bodykey and not bodykey[0].isspace():
                            self.__cur_news['body'] += ' '
                        self.__cur_news['body'] += self.__cur_text
                    else:
                        self.__cur_news['body'] = self.__cur_text
                else:
                    self.__cur_news[self.__cur_stage] = self.__cur_text
                self.__cur_text = ''
            if self.__cur_stage == 'title':
                self.__cur_stage = 'date'
            elif self.__cur_stage == 'date':
                self.__cur_stage = 'body'

    def start_a(self, attrs):
        if self.__innews and self.__cur_stage == 'date':
            href = self.get_attr_value(attrs, 'href')
            if href:
                if not href.startswith('http://'):
                    if href[0] == '/': href = href[1:]
                    href = 'http://akas.imdb.com/%s' % href
                self.__cur_news['link'] = href

    def _handle_data(self, data):
        if self.__innews:
            self.__cur_text += data
        elif self.__inh1 and self.__intable:
            if data.strip().lower().startswith('news for'):
                self.__innews = 1


class HTMLAmazonReviewsParser(ParserBase):
    """Parser for the "amazon reviews" page of a given movie.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        arparser = HTMLAmazonReviewsParser()
        result = arparser.parse(amazonreviews_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        """Reset the parser."""
        self.__intable = 0
        self.__inh3 = 0
        self.__inreview = 0
        self.__in_kind = 0
        self.__reviews = []
        self.__cur_title = ''
        self.__cur_text = ''
        self.__cur_link = ''
        self.__cur_revkind = ''
    
    def get_data(self):
        """Return the dictionary."""
        if not self.__reviews: return {}
        return {'amazon reviews': self.__reviews}

    def start_table(self, attrs):
        self.__intable = 1

    def end_table(self):
        if self.__inreview:
            self._add_info()
            self.__cur_title = ''
            self.__cur_link = ''
        self.__intable = 0
        self.__inreview = 0

    def start_h3(self, attrs):
        self.__inh3 = 1
        self.__cur_link = ''
        self.__cur_title = ''

    def end_h3(self):
        self.__inh3 = 0

    def start_a(self, attrs):
        if self.__inh3:
            href = self.get_attr_value(attrs, 'href')
            if href:
                if not href.startswith('http://'):
                    if href[0] == '/': href = href[1:]
                    href = 'http://akas.imdb.com/%s' % href
                self.__cur_link = href.strip()

    def end_a(self): pass

    def start_b(self, attrs):
        if self.__inreview:
            self.__in_kind = 1

    def end_b(self):
        self.__in_kind = 0

    def start_p(self, attrs):
        if self.__inreview:
            self._add_info()

    def end_p(self):
        self.__inreview = 0
        self.__cur_title = ''
        self.__cur_link = ''

    def _add_info(self):
        self.__cur_title = self.__cur_title.replace('\n', ' ').strip()
        self.__cur_text = self.__cur_text.replace('\n', ' ').strip()
        self.__cur_link = self.__cur_link.strip()
        self.__cur_revkind = self.__cur_revkind.replace('\n', ' ').strip()
        entry = {}
        if not self.__cur_text: return
        ai = self.__cur_text.rfind(' --', -30)
        author = ''
        if ai != -1:
            author = self.__cur_text[ai+3:]
            self.__cur_text = self.__cur_text[:ai-1]
        if self.__cur_title and self.__cur_title[-1] == ':':
            self.__cur_title = self.__cur_title[:-1]
        if self.__cur_revkind and self.__cur_revkind[-1] == ':':
            self.__cur_revkind = self.__cur_revkind[:-1]
        if self.__cur_title: entry['title'] = self.__cur_title
        if self.__cur_text: entry['review'] = self.__cur_text
        if self.__cur_link: entry['link'] = self.__cur_link
        if self.__cur_revkind: entry['review kind'] = self.__cur_revkind
        if author: entry['review author'] = author
        if entry: self.__reviews.append(entry)
        self.__cur_text = ''
        self.__cur_revkind = ''

    def _handle_data(self, data):
        if self.__inreview:
            if self.__in_kind:
                self.__cur_revkind += data
            else:
                self.__cur_text += data
        elif self.__intable and self.__inh3:
            self.__inreview = 1
            self.__cur_title += data


class HTMLGuestsParser(ParserBase):
    """Parser for the "guest appearances" page of a given tv series.
    The page should be provided as a string, as taken from
    the akas.imdb.com server.  The final result will be a
    dictionary, with a key for every relevant section.

    Example:
        gparser = HTMLGuestsParser()
        result = gparser.parse(guests_html_string)
    """

    # Do not gather names and titles references.
    getRefs = 0

    def _reset(self):
        self._guests = {}
        self._in_guests = 0
        self._inh1 = 0
        self._goth1 = 0
        self._ingtable = 0
        self._inname = 0
        self._curname = ''
        self._curid = ''
        self._inepisode = 0
        self._curepisode = ''

    def get_data(self):
        if not self._guests: return {}
        return {'guests': self._guests}

    def start_h1(self, attrs):
        self._inh1 = 1

    def end_h1(self):
        self._inh1 = 0

    def start_a(self, attrs):
        if self._inname:
            href = self.get_attr_value(attrs, 'href')
            cid = self.re_imdbID.findall(href or '')
            if cid: self._curid = [-1]

    def end_a(self): pass

    def start_table(self, attrs):
        if self._goth1: self._in_guests = 1

    def end_table(self):
        self._goth1 = 0
        self._in_guests = 0

    def start_tr(self, attrs): pass

    def end_tr(self):
        if self._inname:
            self._curepisode = self._curepisode.replace('\n', ' ').replace('  ', ' ').strip()
            if not self._curepisode: self._curepisode = 'UNKNOWN EPISODE'
            self._curname = self._curname.replace('\n', '').strip()
            if self._curname and self._curid:
                name = self._curname.strip()
                note = ''
                bni = name.find('(')
                if bni != -1:
                    eni = name.rfind(')')
                    if eni != -1:
                        note = name[bni:]
                        name = name[:bni].strip()
                sn = name.split(' .... ')
                name = sn[0]
                role = ' '.join(sn[1:]).strip()
                p = Person(name=name, personID=str(self._curid),
                            currentRole=role, accessSystem='http',
                            notes=note)
                self._guests.setdefault(self._curepisode, []).append(p)
        if self._in_guests:
            self._inname = 0
            self._curname = ''
            self._curid = ''
            self._inepisode = 0

    def start_td(self, attrs):
        if self._in_guests:
            colspan = self.get_attr_value(attrs, 'colspan')
            if colspan == '3':
                self._inepisode = 1
                self._curepisode = ''
            else:
                self._inname = 1

    def end_td(self): pass

    def _handle_data(self, data):
        if self._inh1 and data.lower().find('guest appearances') != -1:
            self._goth1 = 1
        elif self._in_guests:
            if self._inname: self._curname += data
            elif self._inepisode: self._curepisode += data


# The used instances.
movie_parser = HTMLMovieParser()
plot_parser = HTMLPlotParser()
movie_awards_parser = HTMLAwardsParser()
taglines_parser = HTMLTaglinesParser()
keywords_parser = HTMLKeywordsParser()
crazycredits_parser = HTMLCrazyCreditsParser()
goofs_parser = HTMLGoofsParser()
alternateversions_parser = HTMLAlternateVersionsParser()
trivia_parser = HTMLAlternateVersionsParser()
soundtrack_parser = HTMLAlternateVersionsParser()
trivia_parser.kind = 'trivia'
soundtrack_parser.kind = 'soundtrack'
quotes_parser = HTMLQuotesParser()
releasedates_parser = HTMLReleaseinfoParser()
ratings_parser = HTMLRatingsParser()
officialsites_parser = HTMLOfficialsitesParser()
externalrev_parser = HTMLOfficialsitesParser()
externalrev_parser.kind = 'external reviews'
newsgrouprev_parser = HTMLOfficialsitesParser()
newsgrouprev_parser.kind = 'newsgroup reviews'
misclinks_parser = HTMLOfficialsitesParser()
misclinks_parser.kind = 'misc links'
soundclips_parser = HTMLOfficialsitesParser()
soundclips_parser.kind = 'sound clips'
videoclips_parser = HTMLOfficialsitesParser()
videoclips_parser.kind = 'video clips'
photosites_parser = HTMLOfficialsitesParser()
photosites_parser.kind = 'photo sites'
connections_parser = HTMLConnectionParser()
tech_parser = HTMLTechParser()
business_parser = HTMLTechParser()
business_parser.kind = 'business'
business_parser.getRefs = 1
locations_parser = HTMLTechParser()
locations_parser.kind = 'locations'
dvd_parser = HTMLDvdParser()
rec_parser = HTMLRecParser()
news_parser = HTMLNewsParser()
amazonrev_parser = HTMLAmazonReviewsParser()
guests_parser = HTMLGuestsParser()

