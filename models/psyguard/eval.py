from typing import Optional, Tuple, Union

import torch
import ujson
from sklearn.metrics import classification_report
from torch import nn
from torch.nn import BCEWithLogitsLoss, CrossEntropyLoss, MSELoss
from transformers import BertConfig, BertModel, BertPreTrainedModel, BertTokenizer
from transformers.modeling_outputs import SequenceClassifierOutput

id2label = {
    "0": "自杀未遂",
    "1": "自杀准备行为",
    "2": "自杀计划",
    "3": "主动自杀意图",
    "4": "被动自杀意图",
    "5": "用户攻击行为",
    "6": "他人攻击行为",
    "7": "自伤行为",
    "8": "自伤意图",
    "9": "关于自杀的探索",
    "10": "与自杀/自伤/攻击行为无关"
  }


def eval_test_set(model, tokenizer, test_set):
    total = len(test_set)
    
    test_preds = []
    test_trues = []
    accuracy = 0
    
    for item in test_set:
        text = item['text']
        label = item['label']
        result = tokenizer(text=text,
                           padding='max_length',
                           max_length=512,
                           truncation=False,
                           add_special_tokens=True,
                           return_token_type_ids=True,
                           return_tensors='pt')

        result = result.to('cuda')
        
        labels = torch.tensor([label]).cuda()
        result['labels'] = labels
        with torch.no_grad():
            outputs = model(**result)
        predictions = torch.sigmoid(outputs.logits).ge(0.5).int()
        golden_labels = labels.int()
        # print(predictions)
        # print(golden_labels)
        

        batch_accuracy = sum(row.all().int().item() for row in (predictions == golden_labels))
        accuracy += batch_accuracy

        for row in (predictions == golden_labels):
            item['predict_label'] = predictions[0].detach().cpu().tolist()
            if row.all().int().item() == 0:
                # 预测错误
                item['flag'] = False
            else:
                item['flag'] = True

        test_preds.extend(list(predictions.detach().cpu().numpy()))
        test_trues.extend(list(golden_labels.detach().cpu().numpy()))

    print(f'accuracy: {accuracy/total}')
    report = classification_report(test_trues, test_preds, digits=5)
    print(f'report: \n{report}')
    
class RobertaClassificationHead(nn.Module):
    """Head for sentence-level classification tasks."""
    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        classifier_dropout = (config.classifier_dropout
                              if config.classifier_dropout is not None else
                              config.hidden_dropout_prob)
        self.dropout = nn.Dropout(classifier_dropout)
        self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

    def forward(self, features, **kwargs):
        x = features[:, 0, :]  # take <s> token (equiv. to [CLS])
        x = self.dropout(x)
        x = self.dense(x)
        x = torch.tanh(x)
        x = self.dropout(x)
        x = self.out_proj(x)
        return x


class RobertaForSequenceClassification(BertPreTrainedModel):
    def __init__(self, config, model_name_or_path):
        super().__init__(config)
        self.num_labels = config.num_labels
        self.config = config

        self.roberta = BertModel.from_pretrained(model_name_or_path)
        self.classifier = RobertaClassificationHead(config)

        # Initialize weights and apply final processing
        self.post_init()

    def forward(
            self,
            input_ids: Optional[torch.LongTensor] = None,
            attention_mask: Optional[torch.FloatTensor] = None,
            token_type_ids: Optional[torch.LongTensor] = None,
            position_ids: Optional[torch.LongTensor] = None,
            head_mask: Optional[torch.FloatTensor] = None,
            inputs_embeds: Optional[torch.FloatTensor] = None,
            labels: Optional[torch.LongTensor] = None,
            output_attentions: Optional[bool] = None,
            output_hidden_states: Optional[bool] = None,
            return_dict: Optional[bool] = None
    ) -> Union[Tuple[torch.Tensor], SequenceClassifierOutput]:
        r"""
        labels (`torch.LongTensor` of shape `(batch_size,)`, *optional*):
            Labels for computing the sequence classification/regression loss. Indices should be in `[0, ...,
            config.num_labels - 1]`. If `config.num_labels == 1` a regression loss is computed (Mean-Square loss), If
            `config.num_labels > 1` a classification loss is computed (Cross-Entropy).
        """
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        outputs = self.roberta(
            input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            position_ids=position_ids,
            head_mask=head_mask,
            inputs_embeds=inputs_embeds,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )
        sequence_output = outputs[0]
        logits = self.classifier(sequence_output)

        loss = None
        if labels is not None:
            # move labels to correct device to enable model parallelism
            labels = labels.to(logits.device)
            if self.config.problem_type is None:
                if self.num_labels == 1:
                    self.config.problem_type = "regression"
                elif self.num_labels > 1 and (labels.dtype == torch.long
                                              or labels.dtype == torch.int):
                    self.config.problem_type = "single_label_classification"
                else:
                    self.config.problem_type = "multi_label_classification"

            if self.config.problem_type == "regression":
                loss_fct = MSELoss()
                if self.num_labels == 1:
                    loss = loss_fct(logits.squeeze(), labels.squeeze())
                else:
                    loss = loss_fct(logits, labels)
            elif self.config.problem_type == "single_label_classification":
                loss_fct = CrossEntropyLoss()
                loss = loss_fct(logits.view(-1, self.num_labels),
                                labels.view(-1))
            elif self.config.problem_type == "multi_label_classification":
                loss_fct = BCEWithLogitsLoss()
                loss = loss_fct(logits, labels)

        if not return_dict:
            output = (logits, ) + outputs[2:]
            return ((loss, ) + output) if loss is not None else output

        return SequenceClassifierOutput(
            loss=loss,
            logits=logits,
            hidden_states=outputs.hidden_states,
            attentions=outputs.attentions,
        )


if __name__ == '__main__':
    model_path = './'
    config = BertConfig.from_pretrained(
        model_path,
        num_labels=11,
        problem_type="multi_label_classification",
        finetuning_task='text classification')
    
    tokenizer = BertTokenizer.from_pretrained(
        model_path,
        use_fast=False)
    
    model = RobertaForSequenceClassification(config, model_path)
    PATH = f'./pytorch_model.bin'
    model.load_state_dict(torch.load(PATH))
    model.cuda()
    model.eval()

    # prediction for single text
    text = '大学里也自杀过'
    input = tokenizer(text=text,
                      padding='max_length',
                      max_length=512,
                           truncation=False,
                           add_special_tokens=True,
                           return_token_type_ids=True,
                           return_tensors='pt')
    input = input.to('cuda')
    outputs = model(**input)
    prediction = torch.sigmoid(outputs.logits).ge(0.5).int()
    print(prediction)
    # 转换为文本标签
    text_labels = [id2label[str(index)] for index, value in enumerate(prediction[0]) if value == 1]
    print(text_labels)

    # prediction for the test set
    with open('./test.json', 'r', encoding='utf-8') as f:
        test_set = ujson.load(f)
    eval_test_set(model=model, tokenizer=tokenizer, test_set=test_set)