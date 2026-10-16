%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% MFE Technical Report 
% LaTeX Class
% Version 1.0 (December 6, 2024)
%
% This class originates from:
% https://www.LaTeXTemplates.com
% and is based on Creodocs Makoto Technical Report Class v1.0]
%
% Author:
% Vel (vel@latextemplates.com)
%
% License:
% CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/)
%
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


%----------------------------------------------------------------------------------------
%	CLASS CONFIGURATION
%----------------------------------------------------------------------------------------

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{MFETechnicalReport}[2025/06/07 MFE Technical Report Class v1.0]

\newcommand*\MFE@mainlang{english} % Fallback

\DeclareOption{english}{\renewcommand*\MFE@mainlang{english}}
\DeclareOption{german}{\renewcommand*\MFE@mainlang{german}}

% Alle übrigen Optionen an die Basis-Klasse durchreichen
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax


\usepackage{etoolbox} % Required for conditional logic and easily changing commands

\newtoggle{unnumberedsections} % Create toggle for a class option
\settoggle{unnumberedsections}{false} % Default value for the class option
\DeclareOption{unnumberedsections}{\settoggle{unnumberedsections}{true}} % Set the class option toggle if the class option was used in the template

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}} % Pass through any extra options specified to the base class
\ProcessOptions\relax % Process class options

\LoadClass{article} % Load the base class


\RequirePackage[
  english,
  german,
  main=\MFE@mainlang      % <- legt die Hauptsprache fest
]{babel}


%----------------------------------------------------------------------------------------
%	REQUIRED PACKAGES AND MISC CONFIGURATIONS
%----------------------------------------------------------------------------------------
\usepackage{graphicx} % Required for including images
\graphicspath{{figures/}{./}} % Specifies where to look for included images (trailing slash required)

\setlength{\parindent}{0pt} % Paragraph indentation
\setlength{\parskip}{6pt} % Vertical space between paragraphs

\usepackage[bottom, hang]{footmisc} % Force footnotes to the bottom of the page and to the left margin
\setlength{\footnotemargin}{6pt} % Horizontal space between the footnote marker and text

\usepackage{lastpage} % Required to determine the total number of pages

\AtBeginEnvironment{quote}{\itshape\rmfamily} % Style quotations

\usepackage{appendix} % Required for the appendices section

\usepackage{float} % Allows more precisely positioning floats e.g. \begin{figure}[H]

\usepackage{multicol} % Required for outputting content in multiple columns on demand
\usepackage{placeins}
\usepackage{pdflscape} 
\usepackage{needspace}
%----------------------------------------------------------------------------------------
%	MARGINS
%----------------------------------------------------------------------------------------

\usepackage[
	top=3cm, % Top margin
	bottom=3cm, % Bottom margin
	left=1.75cm, % Left margin
	right=1.75cm, % Right margin
	footskip=1.5cm, % Space from the bottom margin to the baseline of the footer
	headsep=0.8cm, % Space from the top margin to the baseline of the header
	headheight=1.5cm, % Height of the header
	columnsep=0.9cm, % Space between text columns (in twocolumn mode)
	%showframe % Uncomment to show frames around the margins for debugging purposes
]{geometry}

%----------------------------------------------------------------------------------------
%	FONTS
%----------------------------------------------------------------------------------------

\usepackage{fontspec} % Required for specifying custom fonts

\defaultfontfeatures{Ligatures=TeX} % To support LaTeX ligatures (e.g. `` and --)
\defaultfontfeatures{Path=Fonts/} % Specify the location of font files

% The sans serif font used explicitly with \textsf{}\sffamily
\setsansfont{IBMPlexSans}[
	UprightFont=*-Light.otf,
	BoldFont=*-SemiBold.otf,
	ItalicFont=*-LightItalic.otf,
	BoldItalicFont=*-SemiBoldItalic.otf
]

\renewcommand*\familydefault{\sfdefault} % Use the sans font by default

% IBM Plex Sans Condensed
\newfontfamily{\plexsanscondensed}{IBMPlexSansCondensed}[
	UprightFont=*-Light.otf,
	BoldFont=*-SemiBold.otf,
	ItalicFont=*-LightItalic.otf,
	BoldItalicFont=*-SemiBoldItalic.otf
]

% The serif font used by default or explicitly with \textrm{}/\rmfamily
\setmainfont{IBMPlexSerif}[
	UprightFont=*-Light.otf,
	BoldFont=*-SemiBold.otf,
	ItalicFont=*-LightItalic.otf,
	BoldItalicFont=*-SemiBoldItalic.otf
]

% The monospace font used explicitly with \texttt{}/\ttfamily
\setmonofont{IBMPlexMono}[
	UprightFont=*-Light.otf,
	BoldFont=*-SemiBold.otf,
	ItalicFont=*-LightItalic.otf,
	BoldItalicFont=*-SemiBoldItalic.otf
]

\newfontface{\plexsansmedium}{IBMPlexSans-Medium.otf} % Plex Sans Medium

%----------------------------------------------------------------------------------------
%	HEADERS AND FOOTERS
%----------------------------------------------------------------------------------------

\usepackage{fancyhdr} % Required for customizing headers and footers
\pagestyle{fancy} % Enable custom headers and footers

\renewcommand{\headrulewidth}{0.5pt} % Top horizontal rule thickness

\fancyhf{} % Clear default headers/footers

\fancyhead[L]{\leftheadercontent} % Left header
\fancyhead[C]{} % Center header
\fancyhead[R]{\rightheadercontent} % Right header

\fancyfoot[L]{} % Left footer
\fancyfoot[C]{\thepage~\ifdefstring{\MFE@mainlang}{german}{von}{of} \pageref{LastPage}} % Center footer
\fancyfoot[R]{} % Right footer

%----------------------------------------------------------------------------------------
%	SECTIONS
%----------------------------------------------------------------------------------------

\usepackage{titlesec} % Required for modifying sections

\iftoggle{unnumberedsections}{ % Conditional logic for the unnumbered sections class options
	\setcounter{secnumdepth}{0} % Don't number sections at any level
}{
	\setcounter{secnumdepth}{3} % Number sections down to subsubsections
}

\titleformat
	{\section} % Section type being modified
	[block] % Section layout type, can be: hang, block, display, runin, leftmargin, rightmargin, drop, wrap, frame
	{\raggedright\Large\plexsansmedium} % Text formatting of the whole section, i.e. label and title
	{\thesection} % Section label (e.g. number) and its formatting
	{7pt} % Horizontal space between the section label and title
	{} % Code before the section title
	[] % Code after the section title

\titlespacing*{\section}{0pt}{0.75\baselineskip}{4pt} % Spacing around section titles, the order is: left, before and after

%------------------------------------------------

\titleformat
	{\subsection} % Section type being modified
	[block] % Section layout type, can be: hang, block, display, runin, leftmargin, rightmargin, drop, wrap, frame
	{\raggedright\plexsansmedium} % Text formatting of the whole section, i.e. label and title
	{\thesubsection} % Section label (e.g. number) and its formatting
	{5pt} % Horizontal space between the section label and title
	{} % Code before the section title
	[] % Code after the section title

\titlespacing*{\subsection}{0pt}{0.75\baselineskip}{0pt} % Spacing around section titles, the order is: left, before and after

%------------------------------------------------

\titleformat
	{\subsubsection} % Section type being modified
	[block] % Section layout type, can be: hang, block, display, runin, leftmargin, rightmargin, drop, wrap, frame
	{\raggedright\bfseries\small} % Text formatting of the whole section, i.e. label and title
	{\thesubsubsection} % Section label (e.g. number) and its formatting
	{5pt} % Horizontal space between the section label and title
	{} % Code before the section title
	[] % Code after the section title

\titlespacing*{\subsubsection}{0pt}{0.5\baselineskip}{0pt} % Spacing around section titles, the order is: left, before and after

%------------------------------------------------

\titleformat
	{\paragraph} % Section type being modified
	[runin] % Section layout type, can be: hang, block, display, runin, leftmargin, rightmargin, drop, wrap, frame
	{\bfseries\small} % Text formatting of the whole section, i.e. label and title
	{} % Section label (e.g. number) and its formatting
	{0pt} % Horizontal space between the section label and title
	{} % Code before the section title
	[~~~~] % Code after the section title

\titlespacing*{\paragraph}
  {0pt}    % linker Einzug
  {\medskipamount} % Abstand *vor* \paragraph
  {0em}    % Abstand *nach* \paragraph (Textabstand)

%----------------------------------------------------------------------------------------
%	TABLE OF CONTENTS
%----------------------------------------------------------------------------------------

\usepackage{titletoc} % Required for manipulating the table of contents

\setcounter{tocdepth}{1} % Show entries in the table of contents down to sections

\titlecontents{section} % Section type being modified
	[0pt] % Left indentation
	{\vspace{-\parskip}} % Before code
	{\plexsansmedium\thecontentslabel.~~} % Formatting of numbered sections of this type
	{\plexsansmedium} % Formatting of numberless sections of this type
	{\titlerule*[4pt]{.}\plexsansmedium\contentspage} % Formatting of the filler to the right of the heading and the page number
	[] % After code

%----------------------------------------------------------------------------------------
%	COLORS
%----------------------------------------------------------------------------------------

\usepackage[usenames, svgnames]{xcolor} % Required for defining and using custom colors

\definecolor{tumblue}{HTML}{0065BD} %TUM BLue
\definecolor{tumdarkblue}{HTML}{005189}
\definecolor{tumorange}{HTML}{E37222}
\definecolor{tumlightorange}{HTML}{F7B11E}
\definecolor{tumlightblue}{HTML}{64A0C8}
\definecolor{tummiddleblue}{HTML}{98C6EA}
\definecolor{tumgreen}{HTML}{A2AD00}
\definecolor{tumlightgreen}{HTML}{9FBA36}
\definecolor{tumpurple}{HTML}{B55CA5}
\definecolor{tumlightpurple}{HTML}{8F81EA}
\definecolor{tumgrey}{HTML}{808080}
\definecolor{tumlightgrey}{HTML}{CCCCCC}

%----------------------------------------------------------------------------------------
%	MATH
%----------------------------------------------------------------------------------------
\usepackage[tbtags]{mathtools}
\usepackage{amssymb, amsthm, siunitx}

\usepackage[nolimits]{cmupint}
\usepackage{parskip}

%----------------------------------------------------------------------------------------
%	CHEMISTRY
%----------------------------------------------------------------------------------------
\usepackage{mhchem}

%----------------------------------------------------------------------------------------
%	BIBLIOGRAPHY
%----------------------------------------------------------------------------------------

\usepackage[
	backend=bibtex, % bibtex instead of biber (biber is not installed here) for compiling the bibliography
	citestyle=numeric-comp, % In-text citation style
	bibstyle=numeric, % Bibliography style
	natbib=true,
	maxbibnames=99,
	defernumbers=true, 
	sorting=none, 
	url=false
]{biblatex}

%----------------------------------------------------------------------------------------
%	TABLES
%----------------------------------------------------------------------------------------

\usepackage{booktabs} % Required for better horizontal rules in tables

\usepackage{array} % Required for manipulating table columns
\usepackage{multirow}
\renewcommand{\arraystretch}{1.25} % Increase the height of table rows

\newcolumntype{R}[1]{>{\raggedleft\arraybackslash}p{#1}} % Define a new right-aligned paragraph column type
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}} % Define a new left-aligned (no justification) paragraph column type
\newcolumntype{C}[1]{>{\centering\arraybackslash}p{#1}} % Define a new centered paragraph column type


%----------------------------------------------------------------------------------------
%	CAPTIONS
%----------------------------------------------------------------------------------------

\usepackage{caption} % Required for customizing captions
\usepackage{subcaption}
\captionsetup{skip=6pt} % Vertical whitespace between figures/tables and the caption (default is 10pt)
\captionsetup{font={bf, small}} % Define caption font style
\captionsetup{
	justification=raggedright, 
	singlelinecheck=false, % Left-align captions
	labelfont=bf,      % "Abbildung"/"Tabelle" fett
 	textfont=normalfont  % restliche Bildunterschrift normal
	}
  

%----------------------------------------------------------------------------------------
%	LISTS
%----------------------------------------------------------------------------------------

\usepackage{enumitem} % Required for list customization

\setlist{itemsep=0pt, topsep=0pt} % Customize spacing around and inside lists

\renewcommand{\labelenumi}{\arabic{enumi}.} % Customize the first level numbered list characters
\renewcommand{\labelenumii}{\alph{enumii}.} % Customize the second level numbered list characters
\renewcommand{\labelenumiii}{\roman{enumiii}.} % Customize the third level numbered list characters

\renewcommand{\labelitemi}{\Large\raisebox{-1.5pt}{\textbullet}} % Customize the first level bullet point character
\renewcommand{\labelitemii}{\Large\raisebox{-1.5pt}{--}} % Customize the second level bullet point character
\renewcommand{\labelitemiii}{\Large\raisebox{-1.5pt}{-}} % Customize the third level bullet point character

%----------------------------------------------------------------------------------------
%	LINKS
%----------------------------------------------------------------------------------------

\usepackage{hyperref} % Required for links

\hypersetup{
	colorlinks=true, % Whether to color the text of links
	urlcolor=tumblue, % Color for \url and \href links
	linkcolor=tumdarkblue, % Color for \nameref links
	citecolor=tumdarkblue, % Color of reference citations
}

%----------------------------------------------------------------------------------------
%	CODE LISTINGS
%----------------------------------------------------------------------------------------

\usepackage{listings} % Required for formatted code blocks

\lstset{
	numbers=left, % Line numbers location
	numbersep=6pt, % Whitespace to the right of line numbers
	numberstyle=\tiny\it, % Line numbers font style
	frame=single, % Border
	basicstyle=\tt\scriptsize, % Code font style
	breaklines=true, % Break long lines into multiple lines automatically
	aboveskip=1.5\baselineskip, % Vertical whitespace before the listing
	tabsize=3, % How many space to a tab
}

%----------------------------------------------------------------------------------------
%	CUSTOM COMMANDS
%----------------------------------------------------------------------------------------

\newcommand{\reporttitle}[1]{\renewcommand{\reporttitle}{#1}}
\newcommand{\reportsubtitle}[1]{\renewcommand{\reportsubtitle}{#1}}
\newcommand{\reportauthors}[1]{\renewcommand{\reportauthors}{#1}}
\newcommand{\reportdate}[1]{\renewcommand{\reportdate}{#1}}

\newcommand{\leftheadercontent}[1]{\renewcommand{\leftheadercontent}{#1}}
\newcommand{\rightheadercontent}[1]{\renewcommand{\rightheadercontent}{#1}}


\makeatletter
\renewcommand\@makefntext[1]{%
  \parindent 1em%
  \noindent\makebox[1.0em][l]{\textsuperscript{\@thefnmark}}\hspace{0.1em}#1} %Abstand zwischen Paragraph und Text
\makeatother

