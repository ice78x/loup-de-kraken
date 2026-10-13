from . import breakout_retest, donchian, news, rejection, trend

STRATEGIES = {
    breakout_retest.NAME: breakout_retest.find,
    rejection.NAME: rejection.find,
    trend.NAME: trend.find,
    donchian.NAME: donchian.find,
    news.NAME: news.find,
}
