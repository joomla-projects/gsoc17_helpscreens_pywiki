#!/usr/bin/python
# -*- coding: utf-8 -*-
r"""
Template harvesting script.

Usage:

* python pwb.py harvest_template -transcludes:"..." \
    template_parameter PID [template_parameter PID]
* python pwb.py harvest_template [generators] -template:"..." \
    template_parameter PID [template_parameter PID]

This will work on all pages that transclude the template in the article
namespace

These command line parameters can be used to specify which pages to work on:

&params;

Examples:

    python pwb.py harvest_template -lang:nl -cat:Sisoridae -namespace:0 \
        -template:"Taxobox straalvinnige" orde P70 familie P71 geslacht P74

"""
#
# (C) Multichill, Amir, 2013
# (C) Pywikibot team, 2013-2017
#
# Distributed under the terms of MIT License.
#
from __future__ import absolute_import, unicode_literals

__version__ = '$Id$'
#

import signal

willstop = False


def _signal_handler(signal, frame):
    global willstop
    if not willstop:
        willstop = True
        print('Received ctrl-c. Finishing current item; '
              'press ctrl-c again to abort.')  # noqa
    else:
        raise KeyboardInterrupt


signal.signal(signal.SIGINT, _signal_handler)

import pywikibot
from pywikibot import pagegenerators as pg, WikidataBot, textlib

docuReplacements = {'&params;': pywikibot.pagegenerators.parameterHelp}


class HarvestRobot(WikidataBot):

    """A bot to add Wikidata claims."""

    def __init__(self, generator, templateTitle, fields):
        """
        Constructor.

        @param generator: A generator that yields Page objects
        @type generator: iterator
        @param templateTitle: The template to work on
        @type templateTitle: str
        @param fields: A dictionary of fields that are of use to us
        @type fields: dict
        """
        self.availableOptions['always'] = True
        super(HarvestRobot, self).__init__()
        self.generator = generator
        self.templateTitle = templateTitle.replace(u'_', u' ')
        # TODO: Make it a list which also includes the redirects to the template
        self.fields = fields
        self.cacheSources()
        self.templateTitles = self.getTemplateSynonyms(self.templateTitle)
        self.linkR = textlib.compileLinkR()

    def getTemplateSynonyms(self, title):
        """Fetch redirects of the title, so we can check against them."""
        temp = pywikibot.Page(pywikibot.Site(), title, ns=10)
        if not temp.exists():
            pywikibot.error(u'Template %s does not exist.' % temp.title())
            exit()

        # Put some output here since it can take a while
        pywikibot.output('Finding redirects...')
        if temp.isRedirectPage():
            temp = temp.getRedirectTarget()
        titles = [page.title(withNamespace=False)
                  for page in temp.getReferences(redirectsOnly=True,
                                                 namespaces=[10],
                                                 follow_redirects=False)]
        titles.append(temp.title(withNamespace=False))
        return titles

    def _template_link_target(self, item, link_text):
        link = pywikibot.Link(link_text)
        linked_page = pywikibot.Page(link)

        if not linked_page.exists():
            pywikibot.output('%s does not exist so it cannot be linked. '
                             'Skipping.' % (linked_page))
            return

        if linked_page.isRedirectPage():
            linked_page = linked_page.getRedirectTarget()

        try:
            linked_item = pywikibot.ItemPage.fromPage(linked_page)
        except pywikibot.NoPage:
            linked_item = None

        if not linked_item or not linked_item.exists():
            pywikibot.output('%s does not have a wikidata item to link with. '
                             'Skipping.' % (linked_page))
            return

        if linked_item.title() == item.title():
            pywikibot.output('%s links to itself. Skipping.' % (linked_page))
            return

        return linked_item

    def treat(self, page, item):
        """Process a single page/item."""
        if willstop:
            raise KeyboardInterrupt
        self.current_page = page
        item.get()
        if set(self.fields.values()) <= set(item.claims.keys()):
            pywikibot.output('%s item %s has claims for all properties. '
                             'Skipping.' % (page, item.title()))
            return

        templates = page.raw_extracted_templates
        for (template, fielddict) in templates:
            # Clean up template
            try:
                template = pywikibot.Page(page.site, template,
                                          ns=10).title(withNamespace=False)
            except pywikibot.exceptions.InvalidTitle:
                pywikibot.error(
                    "Failed parsing template; '%s' should be the template name."
                    % template)
                continue
            # We found the template we were looking for
            if template in self.templateTitles:
                for field, value in fielddict.items():
                    field = field.strip()
                    value = value.strip()
                    if not field or not value:
                        continue

                    # This field contains something useful for us
                    if field in self.fields:
                        # Check if the property isn't already set
                        claim = pywikibot.Claim(self.repo, self.fields[field])
                        if claim.getID() in item.get().get('claims'):
                            pywikibot.output(
                                'A claim for %s already exists. Skipping.'
                                % claim.getID())
                            # TODO: Implement smarter approach to merging
                            # harvested values with existing claims esp.
                            # without overwriting humans unintentionally.
                        else:
                            if claim.type == 'wikibase-item':
                                # Try to extract a valid page
                                match = pywikibot.link_regex.search(value)
                                if match:
                                    link_text = match.group(1)
                                else:
                                    link_text = value

                                linked_item = self._template_link_target(
                                    item, link_text)
                                if not linked_item:
                                    continue

                                claim.setTarget(linked_item)
                            elif claim.type in ('string', 'external-id'):
                                claim.setTarget(value.strip())
                            elif claim.type == 'url':
                                match = self.linkR.search(value)
                                if not match:
                                    continue
                                claim.setTarget(match.group('url'))
                            elif claim.type == 'commonsMedia':
                                commonssite = pywikibot.Site('commons',
                                                             'commons')
                                imagelink = pywikibot.Link(value,
                                                           source=commonssite,
                                                           defaultNamespace=6)
                                image = pywikibot.FilePage(imagelink)
                                if image.isRedirectPage():
                                    image = pywikibot.FilePage(
                                        image.getRedirectTarget())
                                if not image.exists():
                                    pywikibot.output(
                                        "{0} doesn't exist. I can't link to it"
                                        ''.format(image.title(asLink=True)))
                                    continue
                                claim.setTarget(image)
                            else:
                                pywikibot.output(
                                    '%s is not a supported datatype.'
                                    % claim.type)
                                continue

                            # A generator might yield pages from multiple sites
                            self.user_add_claim(item, claim, page.site)


def main(*args):
    """
    Process command line arguments and invoke bot.

    If args is an empty list, sys.argv is used.

    @param args: command line arguments
    @type args: list of unicode
    """
    commandline_arguments = []
    template_title = u''

    # Process global args and prepare generator args parser
    local_args = pywikibot.handle_args(args)
    gen = pg.GeneratorFactory()

    for arg in local_args:
        if arg.startswith('-template'):
            if len(arg) == 9:
                template_title = pywikibot.input(
                    u'Please enter the template to work on:')
            else:
                template_title = arg[10:]
        elif gen.handleArg(arg):
            if arg.startswith(u'-transcludes:'):
                template_title = arg[13:]
        else:
            commandline_arguments.append(arg)

    if not template_title:
        pywikibot.error(
            'Please specify either -template or -transcludes argument')
        return

    if len(commandline_arguments) % 2:
        raise ValueError  # or something.
    fields = {}

    for i in range(0, len(commandline_arguments), 2):
        fields[commandline_arguments[i]] = commandline_arguments[i + 1]

    generator = gen.getCombinedGenerator(preload=True)
    if not generator:
        gen.handleArg(u'-transcludes:' + template_title)
        generator = gen.getCombinedGenerator(preload=True)

    bot = HarvestRobot(generator, template_title, fields)
    bot.run()


if __name__ == "__main__":
    main()
