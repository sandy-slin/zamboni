#!/usr/bin/env python

import amo
from addons.models import AddonCategory, Category


def run():
    cats = Category.objects.filter(type=amo.ADDON_PERSONA)
    fx_cats = cats.filter(application_id=amo.FIREFOX.id)

    tb_cats = cats.filter(application_id=amo.THUNDERBIRD.id)
    for tb_cat in tb_cats:
        try:
            fx_cat = fx_cats.filter(slug=tb_cat.slug)[0]
        except IndexError:
            print 'Could not find Firefox category for "%s"' % tb_cat.slug
        else:
            print 'Move addon from Thunderbird "%s" to Firefox "%s"' % (
                fx_cat.slug, tb_cat.slug)
            AddonCategory.objects.filter(category=tb_cat).delete()
    tb_cats.delete()

    # TODO: Eventually get rid of `application_id` for all Firefox categories.
    #fx_cats.update(application=None)