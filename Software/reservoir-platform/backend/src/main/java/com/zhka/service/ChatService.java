package com.zhka.service;

import com.zhka.dto.ChatData;
import com.zhka.dto.NavigateCommand;
import com.zhka.dto.StreamEvent;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.List;

/**
 * 对话编排：把 Dify 的原始增量合并成前端可用的「正文增量 + 跳转事件 + 结束事件」。
 *
 * <p>处理思路：
 * <ol>
 *   <li>累积 Dify 的增量文本，剥离 {@code <think>} 思维链与 {@code [[jump:...]]} 标记后，
 *       只把「新增的正文」作为 text 事件下发</li>
 *   <li>同时对累积全文做跳转指令探测，一旦出现完整指令就下发 navigate 事件（只发一次）</li>
 *   <li>流结束时兜底再解析一次，避免指令恰好被拆在最后一块里</li>
 * </ol>
 */
@Service
public class ChatService {

    public static final String EMPTY_QUERY_MESSAGE = "问题内容不能为空";

    private final DifyService difyService;
    private final NavigateService navigateService;
    private final PlatformRuntimeService runtime;

    public ChatService(DifyService difyService, NavigateService navigateService, PlatformRuntimeService runtime) {
        this.difyService = difyService;
        this.navigateService = navigateService;
        this.runtime = runtime;
    }

    /** 流式对话：返回归一化后的事件流（不含任何 Web/SSE 细节） */
    public Flux<StreamEvent> stream(String rawQuery, String conversationId, List<String> fileIds) {
        String query = normalizeQuery(rawQuery);
        boolean hasFiles = fileIds != null && !fileIds.isEmpty();
        if (query.isEmpty() && !hasFiles) {
            return Flux.just(StreamEvent.error(EMPTY_QUERY_MESSAGE));
        }

        // 把平台当前运行数据附在问题前，AI 在问水位/闸门/传感器/告警时可直接使用
        String enriched = runtime.augment(query);

        // 累加状态按订阅创建，避免并发请求之间互相污染
        return Flux.defer(() -> difyService.streamChat(enriched, conversationId, fileIds)
                .concatMap(new StreamAccumulator()::accept));
    }

    /** 阻塞式对话（调试用）：直接把清洗后的正文返回 */
    public Mono<ChatData> chatOnce(String rawQuery, String conversationId) {
        return difyService.chatOnce(runtime.augment(normalizeQuery(rawQuery)), conversationId)
                .map(data -> {
                    NavigateService.Parsed parsed = navigateService.parse(data.reply());
                    return new ChatData(parsed.text(), data.conversationId());
                });
    }

    public static String normalizeQuery(String rawQuery) {
        return rawQuery == null ? "" : rawQuery.trim();
    }

    /** 单次订阅内的流式累积状态 */
    private final class StreamAccumulator {

        private final StringBuilder raw = new StringBuilder();
        /** 已经下发给前端的正文字数（剥离思维链后的口径） */
        private int emittedLength;
        /** 是否已经下发过导航指令，避免重复跳转 */
        private boolean navigated;

        Flux<StreamEvent> accept(StreamEvent event) {
            String type = event.type();
            if ("text".equals(type)) {
                return onText(event);
            }
            if ("done".equals(type)) {
                return onDone(event);
            }
            return Flux.just(event);
        }

        private Flux<StreamEvent> onText(StreamEvent event) {
            raw.append(event.content());

            String visible = navigateService.stripJumpMarks(navigateService.stripThink(raw.toString()));
            String delta = visible.length() > emittedLength ? visible.substring(emittedLength) : "";
            emittedLength = visible.length();

            Flux<StreamEvent> out = delta.isEmpty()
                    ? Flux.empty()
                    : Flux.just(StreamEvent.text(delta));

            // 文本里出现完整指令时，尽早通知前端跳转
            if (!navigated) {
                NavigateCommand command = navigateService.detect(raw.toString());
                if (command != null) {
                    navigated = true;
                    out = out.concatWith(Flux.just(StreamEvent.navigate(command)));
                }
            }
            return out;
        }

        private Flux<StreamEvent> onDone(StreamEvent event) {
            if (navigated) {
                return Flux.just(event);
            }
            NavigateCommand command = navigateService.parse(raw.toString()).command();
            if (command == null) {
                return Flux.just(event);
            }
            navigated = true;
            return Flux.just(event, StreamEvent.navigate(command));
        }
    }
}
